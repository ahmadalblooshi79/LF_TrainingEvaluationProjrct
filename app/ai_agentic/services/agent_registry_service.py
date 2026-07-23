"""سجل الوكلاء المركزي."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.ai_agentic import config as ag_config
from app.ai_agentic.exceptions import DuplicateAgentKeyError, WorkflowNotFoundError
from app.ai_agentic.models import AiAgent, AiAgentRun
from app.ai_agentic.services.audit_log_service import AuditLogService


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class AgentRegistryService:
    def __init__(self, db: Session):
        self.db = db
        self.audit = AuditLogService(db)

    def register_agent(
        self,
        *,
        agent_key: str,
        display_name: str,
        description: str = "",
        category: str = "system",
        version: str = "1.0.0",
        enabled: bool = True,
        model_name: str = "",
        prompt_version_id: int | None = None,
        default_timeout_seconds: int | None = None,
        max_retries: int | None = None,
        user_id: int | None = None,
    ) -> AiAgent:
        key = (agent_key or "").strip()
        if not key:
            raise DuplicateAgentKeyError("مفتاح الوكيل فارغ.")
        existing = self.get_agent(key)
        if existing:
            raise DuplicateAgentKeyError(f"الوكيل موجود مسبقاً: {key}")
        row = AiAgent(
            agent_key=key,
            display_name=(display_name or key).strip(),
            description=description or None,
            category=(category or "system").strip(),
            version=(version or "1.0.0").strip(),
            enabled=bool(enabled),
            model_name=(model_name or ag_config.AI_DEFAULT_MODEL or "").strip(),
            prompt_version_id=prompt_version_id,
            default_timeout_seconds=int(
                default_timeout_seconds
                if default_timeout_seconds is not None
                else ag_config.AI_DEFAULT_TIMEOUT
            ),
            max_retries=int(
                max_retries if max_retries is not None else ag_config.AI_DEFAULT_MAX_RETRIES
            ),
            created_at=_utcnow(),
            updated_at=_utcnow(),
        )
        self.db.add(row)
        try:
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise DuplicateAgentKeyError(f"الوكيل موجود مسبقاً: {key}") from exc
        self.db.refresh(row)
        self.audit.log(
            action_type="agent.register",
            entity_type="ai_agent",
            entity_id=row.agent_key,
            user_id=user_id,
            new_value={"agent_key": row.agent_key, "version": row.version},
        )
        return row

    def get_agent(self, agent_key: str) -> AiAgent | None:
        return (
            self.db.query(AiAgent)
            .filter(AiAgent.agent_key == (agent_key or "").strip())
            .first()
        )

    def get_agent_or_raise(self, agent_key: str) -> AiAgent:
        row = self.get_agent(agent_key)
        if not row:
            raise WorkflowNotFoundError(f"الوكيل غير مسجّل: {agent_key}")
        return row

    def list_agents(self, *, enabled_only: bool = False) -> list[AiAgent]:
        q = self.db.query(AiAgent)
        if enabled_only:
            q = q.filter(AiAgent.enabled.is_(True))
        return q.order_by(AiAgent.agent_key.asc()).all()

    def enable_agent(self, agent_key: str, *, user_id: int | None = None) -> AiAgent:
        return self._set_enabled(agent_key, True, user_id=user_id)

    def disable_agent(self, agent_key: str, *, user_id: int | None = None) -> AiAgent:
        return self._set_enabled(agent_key, False, user_id=user_id)

    def _set_enabled(self, agent_key: str, enabled: bool, *, user_id: int | None) -> AiAgent:
        row = self.get_agent_or_raise(agent_key)
        old = row.enabled
        row.enabled = bool(enabled)
        row.updated_at = _utcnow()
        self.db.commit()
        self.db.refresh(row)
        self.audit.log(
            action_type="agent.enable" if enabled else "agent.disable",
            entity_type="ai_agent",
            entity_id=row.agent_key,
            user_id=user_id,
            old_value={"enabled": old},
            new_value={"enabled": row.enabled},
        )
        return row

    def update_version(self, agent_key: str, version: str, *, user_id: int | None = None) -> AiAgent:
        row = self.get_agent_or_raise(agent_key)
        old = row.version
        row.version = (version or "").strip() or row.version
        row.updated_at = _utcnow()
        self.db.commit()
        self.audit.log(
            action_type="agent.update_version",
            entity_type="ai_agent",
            entity_id=row.agent_key,
            user_id=user_id,
            old_value={"version": old},
            new_value={"version": row.version},
        )
        return row

    def update_model(self, agent_key: str, model_name: str, *, user_id: int | None = None) -> AiAgent:
        row = self.get_agent_or_raise(agent_key)
        old = row.model_name
        row.model_name = (model_name or "").strip()
        row.updated_at = _utcnow()
        self.db.commit()
        self.audit.log(
            action_type="agent.update_model",
            entity_type="ai_agent",
            entity_id=row.agent_key,
            user_id=user_id,
            old_value={"model_name": old},
            new_value={"model_name": row.model_name},
        )
        return row

    def update_timeout(self, agent_key: str, seconds: int, *, user_id: int | None = None) -> AiAgent:
        row = self.get_agent_or_raise(agent_key)
        old = row.default_timeout_seconds
        row.default_timeout_seconds = max(5, int(seconds))
        row.updated_at = _utcnow()
        self.db.commit()
        self.audit.log(
            action_type="agent.update_timeout",
            entity_type="ai_agent",
            entity_id=row.agent_key,
            user_id=user_id,
            old_value={"timeout": old},
            new_value={"timeout": row.default_timeout_seconds},
        )
        return row

    def update_retry_count(self, agent_key: str, retries: int, *, user_id: int | None = None) -> AiAgent:
        row = self.get_agent_or_raise(agent_key)
        old = row.max_retries
        row.max_retries = max(0, min(10, int(retries)))
        row.updated_at = _utcnow()
        self.db.commit()
        self.audit.log(
            action_type="agent.update_retries",
            entity_type="ai_agent",
            entity_id=row.agent_key,
            user_id=user_id,
            old_value={"max_retries": old},
            new_value={"max_retries": row.max_retries},
        )
        return row

    def last_run_for_agent(self, agent_id: int) -> AiAgentRun | None:
        return (
            self.db.query(AiAgentRun)
            .filter(AiAgentRun.agent_id == agent_id)
            .order_by(AiAgentRun.id.desc())
            .first()
        )

    def resolve_effective_model(self, row: AiAgent) -> tuple[str, str]:
        """يعيد (model_name, model_source) حيث source = agent | default."""
        explicit = (row.model_name or "").strip()
        if explicit:
            return explicit, "agent"
        from app.ai_local_engine.services.ai_service import AIService
        from app.ai_agentic import config as ag_config

        settings_model = ""
        try:
            settings_model = (AIService(self.db).get_settings().model_name or "").strip()
        except Exception:  # noqa: BLE001
            settings_model = ""
        fallback = settings_model or (ag_config.AI_DEFAULT_MODEL or "").strip()
        return fallback, "default"

    def agent_to_dict(self, row: AiAgent) -> dict[str, Any]:
        from app.ai_agentic.display import agent_display_name_ar
        from app.ai_agentic.formatters import format_duration_ms

        last = self.last_run_for_agent(row.id) if row.id else None
        model_name, model_source = self.resolve_effective_model(row)
        last_label = "لم يُشغَّل"
        if last:
            if last.status == "SUCCESS":
                last_label = "نجاح"
            elif last.status == "WARNING":
                last_label = "تحذير"
            elif last.status == "FAILED":
                last_label = "فشل"
            else:
                last_label = last.status
        return {
            "id": row.id,
            "agent_key": row.agent_key,
            "display_name": row.display_name,
            "display_name_ar": agent_display_name_ar(row.agent_key, row.display_name),
            "description": row.description,
            "category": row.category,
            "version": row.version,
            "enabled": bool(row.enabled),
            "model_name": model_name or "",
            "model_source": model_source,
            "stored_model_name": (row.model_name or "").strip(),
            "prompt_version_id": row.prompt_version_id,
            "default_timeout_seconds": row.default_timeout_seconds,
            "max_retries": row.max_retries,
            "created_at": row.created_at.isoformat(sep=" ", timespec="seconds") if row.created_at else None,
            "updated_at": row.updated_at.isoformat(sep=" ", timespec="seconds") if row.updated_at else None,
            "last_run_status": last.status if last else None,
            "last_run_label": last_label,
            "last_run_at": last.completed_at.isoformat(sep=" ", timespec="seconds")
            if last and last.completed_at
            else (last.started_at.isoformat(sep=" ", timespec="seconds") if last and last.started_at else None),
            "last_run_duration_display": format_duration_ms(last.duration_ms) if last else "—",
        }
