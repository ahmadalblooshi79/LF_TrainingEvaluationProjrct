"""ترحيل آمن لجداول مركز التدريب."""

from __future__ import annotations

import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.ai_training.constants import DOCUMENT_INGESTION_AGENT_KEY, TRAINING_TABLES
from app.ai_training.exceptions import TrainingCenterError
from app.ai_training.paths import ensure_ai_training_dirs
from app.config import DATABASE_URL
from app.database import Base, SessionLocal, engine
from app.paths import data_dir

logger = logging.getLogger(__name__)

MIGRATION_ID = "training_center_b1_v1"


class MigrationSafetyError(TrainingCenterError):
    error_code = "migration_safety_error"
    user_message = "فشلت عملية ترحيل مركز التدريب."


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def sqlite_db_path() -> Path | None:
    if not DATABASE_URL.startswith("sqlite"):
        return None
    raw = DATABASE_URL.replace("sqlite:///", "", 1)
    if raw.startswith("/") and len(raw) > 2 and raw[2] == ":":
        raw = raw[1:]
    p = Path(raw)
    if not p.is_absolute():
        p = Path(data_dir()) / p.name
    return p


def backup_dir() -> Path:
    d = Path(data_dir()) / "backups"
    d.mkdir(parents=True, exist_ok=True)
    return d


def create_database_backup(*, reason: str = "training_b1") -> Path:
    db_path = sqlite_db_path()
    if db_path is None:
        raise MigrationSafetyError("النسخ الاحتياطي التلقائي متاح لـ SQLite فقط.")
    if not db_path.is_file():
        raise MigrationSafetyError(f"ملف قاعدة البيانات غير موجود: {db_path}")
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = backup_dir() / f"exercises_pre_{reason}_{ts}.db"
    shutil.copy2(db_path, dest)
    if not dest.is_file() or dest.stat().st_size != db_path.stat().st_size:
        raise MigrationSafetyError("فشل التحقق من ملف النسخة الاحتياطية.")
    return dest


def _legacy_counts(conn) -> dict[str, int]:
    insp = inspect(conn)
    names = set(insp.get_table_names())
    watch = [t for t in ("ai_settings", "users", "exercises", "ai_agents", "ai_report_sources") if t in names]
    return {t: int(conn.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar() or 0) for t in watch}


def ensure_training_tables() -> None:
    import app.ai_training.models  # noqa: F401

    Base.metadata.create_all(
        bind=engine,
        tables=[
            app.ai_training.models.AiTrainingDocument.__table__,
            app.ai_training.models.AiTrainingDocumentPage.__table__,
            app.ai_training.models.AiTrainingDocumentBlock.__table__,
            app.ai_training.models.AiTrainingDocumentReview.__table__,
            app.ai_training.models.AiTrainingDocumentCorrection.__table__,
            app.ai_training.models.AiTrainingDocumentEvent.__table__,
        ],
    )
    ensure_ai_training_dirs()


def seed_ingestion_agent(db: Session) -> None:
    from app.ai_agentic.models import AiAgent, AiPromptVersion
    from app.ai_agentic.services.agent_registry_service import AgentRegistryService

    # prompt placeholder (غير مستخدم للـ LLM افتراضياً)
    prompt = (
        db.query(AiPromptVersion)
        .filter(AiPromptVersion.prompt_key == "document_ingestion_v1", AiPromptVersion.version == "1.0.0")
        .first()
    )
    if not prompt:
        prompt = AiPromptVersion(
            prompt_key="document_ingestion_v1",
            agent_key=DOCUMENT_INGESTION_AGENT_KEY,
            version="1.0.0",
            system_prompt="Deterministic document ingestion. Do not rewrite content.",
            user_prompt_template="N/A — parser only",
            is_active=True,
            created_at=_utcnow(),
            updated_at=_utcnow(),
        )
        db.add(prompt)
        db.flush()

    reg = AgentRegistryService(db)
    existing = reg.get_agent(DOCUMENT_INGESTION_AGENT_KEY)
    if not existing:
        try:
            reg.register_agent(
                agent_key=DOCUMENT_INGESTION_AGENT_KEY,
                display_name="Document Ingestion Agent",
                description="Extracts text, pages, and blocks from training documents. No institutional learning.",
                category="training",
                version="1.0.0",
                enabled=True,
                model_name="",
                prompt_version_id=prompt.id,
                default_timeout_seconds=300,
                max_retries=0,
            )
        except Exception:
            db.rollback()
            # قد يكون موجوداً بسبب سباق
            pass
    else:
        if existing.prompt_version_id is None:
            existing.prompt_version_id = prompt.id
            existing.updated_at = _utcnow()
            db.commit()


def verify_training_migration() -> dict[str, Any]:
    insp = inspect(engine)
    names = set(insp.get_table_names())
    missing = [t for t in TRAINING_TABLES if t not in names]
    return {
        "ok": not missing,
        "present": [t for t in TRAINING_TABLES if t in names],
        "missing": missing,
        "migration_id": MIGRATION_ID,
    }


def migrate_training_center(*, skip_backup: bool = False) -> dict[str, Any]:
    backup_path = None
    try:
        if not skip_backup and DATABASE_URL.startswith("sqlite"):
            backup_path = create_database_backup(reason="training_migrate")
        with engine.begin() as conn:
            before = _legacy_counts(conn)
        ensure_training_tables()
        db = SessionLocal()
        try:
            seed_ingestion_agent(db)
        finally:
            db.close()
        with engine.begin() as conn:
            after = _legacy_counts(conn)
        for t, b in before.items():
            # السماح بزيادة ai_agents عند بذرة وكيل الاستيعاب فقط
            if t == "ai_agents" and after.get(t, 0) >= b:
                continue
            if after.get(t) != b:
                raise MigrationSafetyError(f"تغير عدد سجلات {t}: قبل={b} بعد={after.get(t)}")
        ver = verify_training_migration()
        if not ver["ok"]:
            raise MigrationSafetyError(f"جداول ناقصة: {ver['missing']}")
        return {"ok": True, "backup_path": str(backup_path) if backup_path else None, "verification": ver, "before": before, "after": after}
    except Exception as exc:
        logger.exception("migrate_training_center failed")
        if backup_path and Path(backup_path).is_file():
            try:
                shutil.copy2(backup_path, sqlite_db_path())
            except Exception:
                logger.exception("restore failed")
        if isinstance(exc, MigrationSafetyError):
            raise
        raise MigrationSafetyError(str(exc)) from exc


def rollback_training_center(*, drop_tables: bool = True) -> dict[str, Any]:
    dropped = []
    if drop_tables and DATABASE_URL.startswith("sqlite"):
        with engine.begin() as conn:
            existing = set(inspect(conn).get_table_names())
            for t in reversed(TRAINING_TABLES):
                if t in existing:
                    conn.execute(text(f"DROP TABLE IF EXISTS {t}"))
                    dropped.append(t)
    return {"ok": True, "dropped": dropped, "verification": verify_training_migration()}
