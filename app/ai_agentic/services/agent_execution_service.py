"""تنفيذ وكيل واحد مع تحديثات قاعدة البيانات."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.ai_agentic.agents import create_agent_instance
from app.ai_agentic.constants import (
    AR_FAILED,
    AR_PENDING,
    AR_RETRYING,
    AR_RUNNING,
    AR_SUCCESS,
    AR_WARNING,
)
from app.ai_agentic.exceptions import (
    AgentDisabledError,
    AgenticDisabledError,
    RetryLimitExceededError,
)
from app.ai_agentic import config as ag_config
from app.ai_agentic.json_util import dumps_json, loads_json
from app.ai_agentic.models import AiAgentRun
from app.ai_agentic.services.agent_registry_service import AgentRegistryService
from app.ai_agentic.services.ai_gateway_service import AIGatewayService
from app.ai_agentic.services.audit_log_service import AiSystemEventService

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class AgentExecutionService:
    def __init__(self, db: Session, gateway: AIGatewayService | None = None):
        self.db = db
        self.gateway = gateway or AIGatewayService(db)
        self.registry = AgentRegistryService(db)
        self.events = AiSystemEventService(db)

    def run_agent_row(
        self,
        agent_run: AiAgentRun,
        *,
        agent_key: str,
        context: dict[str, Any] | None = None,
        force: bool = False,
    ) -> AiAgentRun:
        if not ag_config.is_agentic_runtime_allowed():
            raise AgenticDisabledError()

        reg = self.registry.get_agent_or_raise(agent_key)
        if not reg.enabled and not force:
            raise AgentDisabledError(f"الوكيل معطّل: {agent_key}")

        # منع التنفيذ المزدوج
        if agent_run.status == AR_RUNNING and not force:
            self.events.emit(
                event_type="agent.duplicate_blocked",
                severity="warning",
                component="agent_execution",
                message=f"منع تنفيذ مزدوج للوكيل {agent_key}",
                workflow_run_id=agent_run.workflow_run_id,
                agent_run_id=agent_run.id,
            )
            return agent_run

        max_retries = int(reg.max_retries or 0)
        attempt = int(agent_run.attempt_number or 1)

        agent_run.status = AR_RUNNING
        agent_run.started_at = agent_run.started_at or _utcnow()
        agent_run.model_name = reg.model_name
        agent_run.input_json = dumps_json(context or {})
        agent_run.updated_at = _utcnow()
        self.db.commit()

        instance = create_agent_instance(agent_key, self.db, gateway=self.gateway)
        instance.apply_registry_row(reg)

        last_output = None
        while True:
            agent_run.attempt_number = attempt
            if attempt > 1:
                agent_run.status = AR_RETRYING
                agent_run.updated_at = _utcnow()
                self.db.commit()

            started = _utcnow()
            agent_run.started_at = started
            self.db.commit()

            output = instance.run(context or {}, run_id=agent_run.id)
            last_output = output
            ended = _utcnow()
            duration = int((ended - started).total_seconds() * 1000)

            if output.status == "success":
                agent_run.status = AR_SUCCESS
                agent_run.output_json = dumps_json(output.to_dict())
                agent_run.warning_json = dumps_json(output.warnings) if output.warnings else None
                agent_run.error_json = None
                agent_run.completed_at = ended
                agent_run.duration_ms = duration
                agent_run.prompt_version = instance.prompt_version
                agent_run.knowledge_version = instance.knowledge_version
                agent_run.model_name = (output.metadata or {}).get("model") or reg.model_name
                agent_run.updated_at = _utcnow()
                self.db.commit()
                return agent_run

            if output.status == "warning":
                agent_run.status = AR_WARNING
                agent_run.output_json = dumps_json(output.to_dict())
                agent_run.warning_json = dumps_json(output.warnings)
                agent_run.completed_at = ended
                agent_run.duration_ms = duration
                agent_run.updated_at = _utcnow()
                self.db.commit()
                return agent_run

            # failed
            agent_run.error_json = dumps_json(output.errors or [{"message": "failed"}])
            agent_run.output_json = dumps_json(output.to_dict())
            agent_run.duration_ms = duration
            agent_run.updated_at = _utcnow()

            if attempt > max_retries:
                agent_run.status = AR_FAILED
                agent_run.completed_at = ended
                self.db.commit()
                self.events.emit(
                    event_type="agent.failed",
                    severity="error",
                    component="agent_execution",
                    message=f"فشل الوكيل {agent_key} بعد {attempt} محاولة/محاولات",
                    details=output.errors,
                    workflow_run_id=agent_run.workflow_run_id,
                    agent_run_id=agent_run.id,
                )
                if max_retries >= 0 and attempt > max_retries:
                    # بلغ حد الإعادة
                    pass
                return agent_run

            attempt += 1
            self.db.commit()
            if attempt > max_retries + 1:
                raise RetryLimitExceededError()

        # unreachable
        agent_run.status = AR_FAILED
        agent_run.output_json = dumps_json(last_output.to_dict() if last_output else {})
        agent_run.completed_at = _utcnow()
        self.db.commit()
        return agent_run

    def create_pending_run(
        self,
        *,
        workflow_run_id: int,
        agent_id: int | None,
        sequence_number: int = 1,
        attempt_number: int = 1,
    ) -> AiAgentRun:
        row = AiAgentRun(
            workflow_run_id=workflow_run_id,
            agent_id=agent_id,
            sequence_number=sequence_number,
            status=AR_PENDING,
            attempt_number=attempt_number,
            created_at=_utcnow(),
            updated_at=_utcnow(),
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row
