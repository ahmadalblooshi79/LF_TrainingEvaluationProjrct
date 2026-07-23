"""ترحيل آمن لجداول Agentic AI Foundation."""

from __future__ import annotations

import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.ai_agentic.constants import AGENTIC_TABLES, SYSTEM_HEALTH_AGENT_KEY
from app.ai_agentic.exceptions import MigrationSafetyError
from app.config import DATABASE_URL
from app.database import Base, engine
from app.paths import data_dir

logger = logging.getLogger(__name__)

MIGRATION_ID = "agentic_foundation_v1"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def sqlite_db_path() -> Path | None:
    if not DATABASE_URL.startswith("sqlite"):
        return None
    # sqlite:///path or sqlite:////abs
    raw = DATABASE_URL.replace("sqlite:///", "", 1)
    if raw.startswith("/") and len(raw) > 2 and raw[2] == ":":
        # /C:/...
        raw = raw[1:]
    p = Path(raw)
    if not p.is_absolute():
        p = Path(data_dir()) / p.name
    return p


def backup_dir() -> Path:
    d = Path(data_dir()) / "backups"
    d.mkdir(parents=True, exist_ok=True)
    return d


def create_database_backup(*, reason: str = "agentic") -> Path:
    db_path = sqlite_db_path()
    if db_path is None:
        raise MigrationSafetyError("النسخ الاحتياطي التلقائي متاح لـ SQLite فقط.")
    if not db_path.is_file():
        raise MigrationSafetyError(f"ملف قاعدة البيانات غير موجود: {db_path}")
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = backup_dir() / f"exercises_pre_{reason}_{ts}.db"
    shutil.copy2(db_path, dest)
    if not dest.is_file() or dest.stat().st_size == 0:
        raise MigrationSafetyError("فشل التحقق من ملف النسخة الاحتياطية.")
    if dest.stat().st_size != db_path.stat().st_size:
        raise MigrationSafetyError("حجم النسخة الاحتياطية لا يطابق الأصل.")
    logger.info("database backup created: %s (%s bytes)", dest, dest.stat().st_size)
    return dest


def _legacy_table_counts(conn) -> dict[str, int]:
    insp = inspect(conn)
    names = set(insp.get_table_names())
    watch = [t for t in ("ai_settings", "users", "exercises", "ai_report_sources") if t in names]
    counts: dict[str, int] = {}
    for t in watch:
        counts[t] = int(conn.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar() or 0)
    return counts


def ensure_agentic_tables() -> None:
    """إنشاء جداول agentic عبر metadata + SQL صريح للفهارس."""
    import app.ai_agentic.models  # noqa: F401

    Base.metadata.create_all(
        bind=engine,
        tables=[
            app.ai_agentic.models.AiAgent.__table__,
            app.ai_agentic.models.AiWorkflowRun.__table__,
            app.ai_agentic.models.AiAgentRun.__table__,
            app.ai_agentic.models.AiPromptVersion.__table__,
            app.ai_agentic.models.AiKnowledgeVersion.__table__,
            app.ai_agentic.models.AiAuditLog.__table__,
            app.ai_agentic.models.AiSystemEvent.__table__,
        ],
    )


def seed_system_health_defaults(db: Session) -> None:
    from app.ai_agentic import config as ag_config
    from app.ai_agentic.json_util import dumps_json
    from app.ai_agentic.models import AiAgent, AiKnowledgeVersion, AiPromptVersion

    short_system = "Return valid JSON only. No explanation."
    short_user = 'Return:\n{"status":"ok","message":"Local model is available"}'

    prompt = (
        db.query(AiPromptVersion)
        .filter(
            AiPromptVersion.prompt_key == "system_health_v1",
            AiPromptVersion.version == "1.0.0",
        )
        .first()
    )
    if not prompt:
        prompt = AiPromptVersion(
            prompt_key="system_health_v1",
            agent_key=SYSTEM_HEALTH_AGENT_KEY,
            version="1.0.0",
            system_prompt=short_system,
            user_prompt_template=short_user,
            output_schema_json=dumps_json(
                {"type": "object", "required": ["status", "message"]}
            ),
            is_active=True,
            created_at=_utcnow(),
            updated_at=_utcnow(),
        )
        db.add(prompt)
        db.flush()
    else:
        # تحديث برومبت قصير دون Migration — لا يحذف السجل
        prompt.system_prompt = short_system
        prompt.user_prompt_template = short_user
        prompt.is_active = True
        prompt.updated_at = _utcnow()

    kv = db.query(AiKnowledgeVersion).filter(AiKnowledgeVersion.version == "0.0.0").first()
    if not kv:
        db.add(
            AiKnowledgeVersion(
                version="0.0.0",
                name="Empty foundation",
                description="Placeholder knowledge version for Agentic Foundation (no training data).",
                status="active",
                created_at=_utcnow(),
                updated_at=_utcnow(),
            )
        )

    agent = db.query(AiAgent).filter(AiAgent.agent_key == SYSTEM_HEALTH_AGENT_KEY).first()
    if not agent:
        db.add(
            AiAgent(
                agent_key=SYSTEM_HEALTH_AGENT_KEY,
                display_name="System Health Agent",
                description="Validates Agent Registry, Orchestrator, AI Gateway, Ollama, logging, and DB persistence.",
                category="system",
                version="1.0.0",
                enabled=True,
                model_name=ag_config.AI_DEFAULT_MODEL or "",
                prompt_version_id=prompt.id,
                default_timeout_seconds=int(ag_config.AI_DEFAULT_TIMEOUT),
                max_retries=0,
                created_at=_utcnow(),
                updated_at=_utcnow(),
            )
        )
    else:
        if prompt and agent.prompt_version_id is None:
            agent.prompt_version_id = prompt.id
        # تسريع اختبار الصحة: لا retries افتراضية
        agent.max_retries = 0
        agent.updated_at = _utcnow()
    db.commit()


def verify_agentic_migration() -> dict[str, Any]:
    insp = inspect(engine)
    names = set(insp.get_table_names())
    missing = [t for t in AGENTIC_TABLES if t not in names]
    present = [t for t in AGENTIC_TABLES if t in names]
    return {
        "ok": not missing,
        "present": present,
        "missing": missing,
        "migration_id": MIGRATION_ID,
    }


def migrate_agentic_foundation(*, skip_backup: bool = False) -> dict[str, Any]:
    backup_path: Path | None = None
    before_counts: dict[str, int] = {}
    try:
        if not skip_backup and DATABASE_URL.startswith("sqlite"):
            backup_path = create_database_backup(reason="agentic_migrate")
        with engine.begin() as conn:
            before_counts = _legacy_table_counts(conn)
        ensure_agentic_tables()
        from app.database import SessionLocal

        db = SessionLocal()
        try:
            seed_system_health_defaults(db)
        finally:
            db.close()
        with engine.begin() as conn:
            after_counts = _legacy_table_counts(conn)
        for table, before in before_counts.items():
            after = after_counts.get(table, -1)
            if after != before:
                raise MigrationSafetyError(
                    f"تغير عدد سجلات الجدول القديم {table}: قبل={before} بعد={after}"
                )
        verification = verify_agentic_migration()
        if not verification["ok"]:
            raise MigrationSafetyError(
                f"جداول ناقصة بعد الترحيل: {verification['missing']}"
            )
        return {
            "ok": True,
            "backup_path": str(backup_path) if backup_path else None,
            "before_counts": before_counts,
            "after_counts": after_counts,
            "verification": verification,
        }
    except Exception as exc:
        logger.exception("migrate_agentic_foundation failed")
        if backup_path and backup_path.is_file():
            try:
                restore_database_from_backup(backup_path)
            except Exception:  # noqa: BLE001
                logger.exception("auto-restore after failed migration also failed")
        if isinstance(exc, MigrationSafetyError):
            raise
        raise MigrationSafetyError(str(exc)) from exc


def restore_database_from_backup(backup_path: Path | str) -> Path:
    src = Path(backup_path)
    db_path = sqlite_db_path()
    if db_path is None:
        raise MigrationSafetyError("الاستعادة متاحة لـ SQLite فقط.")
    if not src.is_file():
        raise MigrationSafetyError(f"ملف النسخة الاحتياطية غير موجود: {src}")
    shutil.copy2(src, db_path)
    if db_path.stat().st_size != src.stat().st_size:
        raise MigrationSafetyError("فشل التحقق من الاستعادة.")
    return db_path


def rollback_agentic_foundation(*, drop_tables: bool = True) -> dict[str, Any]:
    """حذف جداول agentic فقط — لا يمس الجداول القديمة."""
    dropped: list[str] = []
    if drop_tables and DATABASE_URL.startswith("sqlite"):
        with engine.begin() as conn:
            insp = inspect(conn)
            existing = set(insp.get_table_names())
            for t in reversed(AGENTIC_TABLES):
                if t in existing:
                    conn.execute(text(f"DROP TABLE IF EXISTS {t}"))
                    dropped.append(t)
    verification = verify_agentic_migration()
    return {
        "ok": True,
        "dropped": dropped,
        "tables_remaining": verification["present"],
    }


def latest_agentic_backup() -> Path | None:
    files = sorted(backup_dir().glob("exercises_pre_agentic*.db"), key=lambda p: p.stat().st_mtime)
    return files[-1] if files else None
