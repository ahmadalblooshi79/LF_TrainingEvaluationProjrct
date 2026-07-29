"""ترحيل Phase B2.1 — Military Structure Analysis."""

from __future__ import annotations

import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.ai_training.exceptions import TrainingCenterError
from app.ai_training.migration import create_database_backup, sqlite_db_path
from app.ai_training.structure_constants import (
    MILITARY_STRUCTURE_AGENT_KEY,
    MILITARY_STRUCTURE_PROMPT_KEY,
    MILITARY_STRUCTURE_PROMPT_VERSION,
    STRUCTURE_TABLES,
)
from app.config import DATABASE_URL
from app.database import Base, SessionLocal, engine

logger = logging.getLogger(__name__)

MIGRATION_ID = "military_structure_b21_v1"

STRUCTURE_DOC_COLUMNS = (
    ("structure_status", "VARCHAR(64) NOT NULL DEFAULT 'NOT_STARTED'"),
    ("latest_structure_run_id", "INTEGER"),
    ("structure_approved_by_user_id", "INTEGER"),
    ("structure_approved_at", "DATETIME"),
    ("structure_locked", "BOOLEAN NOT NULL DEFAULT 0"),
)


class StructureMigrationError(TrainingCenterError):
    error_code = "structure_migration_error"
    user_message = "فشلت عملية ترحيل تحليل البنية العسكرية."


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _legacy_counts(conn) -> dict[str, int]:
    insp = inspect(conn)
    names = set(insp.get_table_names())
    watch = [t for t in ("ai_settings", "users", "exercises", "ai_agents", "ai_training_documents", "ai_training_document_blocks") if t in names]
    return {t: int(conn.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar() or 0) for t in watch}


def _ensure_document_columns() -> list[str]:
    added: list[str] = []
    insp = inspect(engine)
    if "ai_training_documents" not in insp.get_table_names():
        return added
    existing = {c["name"] for c in insp.get_columns("ai_training_documents")}
    with engine.begin() as conn:
        for col, ddl in STRUCTURE_DOC_COLUMNS:
            if col not in existing:
                conn.execute(text(f"ALTER TABLE ai_training_documents ADD COLUMN {col} {ddl}"))
                added.append(col)
    return added


def ensure_structure_tables() -> None:
    import app.ai_training.models  # noqa: F401

    Base.metadata.create_all(
        bind=engine,
        tables=[
            app.ai_training.models.AiTrainingStructureRun.__table__,
            app.ai_training.models.AiTrainingDocumentStructure.__table__,
            app.ai_training.models.AiTrainingStructureCorrection.__table__,
            app.ai_training.models.AiTrainingDocumentOutline.__table__,
            app.ai_training.models.AiTrainingStructureEvent.__table__,
        ],
    )
    _ensure_document_columns()


def seed_structure_agent(db: Session) -> None:
    from app.ai_agentic.models import AiAgent, AiPromptVersion
    from app.ai_agentic.services.agent_registry_service import AgentRegistryService
    from app.ai_training.structure.prompt import SYSTEM_PROMPT, USER_PROMPT_TEMPLATE

    prompt = (
        db.query(AiPromptVersion)
        .filter(
            AiPromptVersion.prompt_key == MILITARY_STRUCTURE_PROMPT_KEY,
            AiPromptVersion.version == MILITARY_STRUCTURE_PROMPT_VERSION,
        )
        .first()
    )
    if not prompt:
        prompt = AiPromptVersion(
            prompt_key=MILITARY_STRUCTURE_PROMPT_KEY,
            agent_key=MILITARY_STRUCTURE_AGENT_KEY,
            version=MILITARY_STRUCTURE_PROMPT_VERSION,
            system_prompt=SYSTEM_PROMPT,
            user_prompt_template=USER_PROMPT_TEMPLATE,
            is_active=True,
            created_at=_utcnow(),
            updated_at=_utcnow(),
        )
        db.add(prompt)
        db.flush()

    from app.ai_training import structure_config as scfg

    reg = AgentRegistryService(db)
    existing = reg.get_agent(MILITARY_STRUCTURE_AGENT_KEY)
    if not existing:
        try:
            reg.register_agent(
                agent_key=MILITARY_STRUCTURE_AGENT_KEY,
                display_name="Military Document Structure Agent",
                description="Analyzes military document structure (headings, numbering, hierarchy). No content interpretation.",
                category="training",
                version="1.0.0",
                enabled=True,
                model_name=scfg.AI_STRUCTURE_MODEL,
                prompt_version_id=prompt.id,
                default_timeout_seconds=int(scfg.AI_STRUCTURE_TIMEOUT_SECONDS),
                max_retries=int(scfg.AI_STRUCTURE_MAX_RETRIES),
            )
        except Exception:
            db.rollback()
    else:
        changed = False
        if existing.prompt_version_id is None:
            existing.prompt_version_id = prompt.id
            changed = True
        if not (existing.model_name or "").strip():
            existing.model_name = scfg.AI_STRUCTURE_MODEL
            changed = True
        if changed:
            existing.updated_at = _utcnow()
            db.commit()
    db.commit()


def verify_structure_migration() -> dict[str, Any]:
    insp = inspect(engine)
    names = set(insp.get_table_names())
    missing = [t for t in STRUCTURE_TABLES if t not in names]
    cols_ok = True
    missing_cols: list[str] = []
    if "ai_training_documents" in names:
        existing = {c["name"] for c in insp.get_columns("ai_training_documents")}
        for col, _ in STRUCTURE_DOC_COLUMNS:
            if col not in existing:
                cols_ok = False
                missing_cols.append(col)
    return {
        "ok": not missing and cols_ok,
        "present": [t for t in STRUCTURE_TABLES if t in names],
        "missing": missing,
        "missing_columns": missing_cols,
        "migration_id": MIGRATION_ID,
    }


def migrate_structure_b21(*, skip_backup: bool = False) -> dict[str, Any]:
    backup_path = None
    try:
        if not skip_backup and DATABASE_URL.startswith("sqlite"):
            backup_path = create_database_backup(reason="structure_b21_migrate")
        with engine.begin() as conn:
            before = _legacy_counts(conn)
        ensure_structure_tables()
        db = SessionLocal()
        try:
            seed_structure_agent(db)
        finally:
            db.close()
        with engine.begin() as conn:
            after = _legacy_counts(conn)
        for t, b in before.items():
            if t == "ai_agents" and after.get(t, 0) >= b:
                continue
            if after.get(t) != b:
                raise StructureMigrationError(f"تغير عدد سجلات {t}: قبل={b} بعد={after.get(t)}")
        ver = verify_structure_migration()
        if not ver["ok"]:
            raise StructureMigrationError(f"جداول/أعمدة ناقصة: {ver}")
        return {
            "ok": True,
            "backup_path": str(backup_path) if backup_path else None,
            "verification": ver,
            "before": before,
            "after": after,
        }
    except Exception as exc:
        logger.exception("migrate_structure_b21 failed")
        if backup_path and Path(backup_path).is_file():
            try:
                shutil.copy2(backup_path, sqlite_db_path())
            except Exception:
                logger.exception("restore failed")
        if isinstance(exc, StructureMigrationError):
            raise
        raise StructureMigrationError(str(exc)) from exc


def rollback_structure_b21(*, drop_tables: bool = True) -> dict[str, Any]:
    dropped = []
    if drop_tables and DATABASE_URL.startswith("sqlite"):
        with engine.begin() as conn:
            existing = set(inspect(conn).get_table_names())
            for t in reversed(STRUCTURE_TABLES):
                if t in existing:
                    conn.execute(text(f"DROP TABLE IF EXISTS {t}"))
                    dropped.append(t)
    return {"ok": True, "dropped": dropped, "verification": verify_structure_migration()}
