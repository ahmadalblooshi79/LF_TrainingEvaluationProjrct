"""خدمات تسجيل التدقيق وأحداث النظام."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.ai_agentic.json_util import dumps_json
from app.ai_agentic.models import AiAuditLog, AiSystemEvent


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class AuditLogService:
    def __init__(self, db: Session):
        self.db = db

    def log(
        self,
        *,
        action_type: str,
        entity_type: str,
        entity_id: str | None = None,
        user_id: int | None = None,
        workflow_run_id: int | None = None,
        agent_run_id: int | None = None,
        old_value: Any = None,
        new_value: Any = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        commit: bool = True,
    ) -> AiAuditLog:
        row = AiAuditLog(
            user_id=user_id,
            action_type=action_type,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id is not None else None,
            workflow_run_id=workflow_run_id,
            agent_run_id=agent_run_id,
            old_value_json=dumps_json(old_value),
            new_value_json=dumps_json(new_value),
            ip_address=(ip_address or "")[:64] or None,
            user_agent=(user_agent or "")[:512] or None,
            created_at=_utcnow(),
        )
        self.db.add(row)
        if commit:
            self.db.commit()
            self.db.refresh(row)
        else:
            self.db.flush()
        return row

    def list_recent(self, *, limit: int = 50) -> list[AiAuditLog]:
        return (
            self.db.query(AiAuditLog)
            .order_by(AiAuditLog.id.desc())
            .limit(max(1, min(limit, 200)))
            .all()
        )


class AiSystemEventService:
    def __init__(self, db: Session):
        self.db = db

    def emit(
        self,
        *,
        event_type: str,
        message: str,
        component: str,
        severity: str = "info",
        details: Any = None,
        workflow_run_id: int | None = None,
        agent_run_id: int | None = None,
        commit: bool = True,
    ) -> AiSystemEvent:
        row = AiSystemEvent(
            event_type=event_type,
            severity=severity,
            component=component,
            message=message or "",
            details_json=dumps_json(details),
            workflow_run_id=workflow_run_id,
            agent_run_id=agent_run_id,
            created_at=_utcnow(),
        )
        self.db.add(row)
        if commit:
            self.db.commit()
            self.db.refresh(row)
        else:
            self.db.flush()
        return row

    def list_recent(self, *, limit: int = 50, severity: str | None = None) -> list[AiSystemEvent]:
        q = self.db.query(AiSystemEvent)
        if severity:
            q = q.filter(AiSystemEvent.severity == severity)
        return q.order_by(AiSystemEvent.id.desc()).limit(max(1, min(limit, 200))).all()
