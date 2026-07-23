"""BaseAgent — أساس قابل لإعادة الاستخدام لكل الوكلاء المستقبليين."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

from sqlalchemy.orm import Session

from app.ai_agentic.exceptions import (
    AgentDisabledError,
    AgentExecutionError,
    AgentOutputValidationError,
    AgentValidationError,
)
from app.ai_agentic.schemas import GatewayResult, StructuredAgentOutput
from app.ai_agentic.services.ai_gateway_service import AIGatewayService
from app.ai_agentic.services.prompt_version_service import (
    KnowledgeVersionService,
    PromptVersionService,
)

logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    agent_key: str = "base_agent"
    name: str = "Base Agent"
    description: str = ""
    version: str = "1.0.0"
    enabled: bool = True
    model_name: str = ""
    prompt_version: str = ""
    knowledge_version: str = ""
    timeout_seconds: int = 120
    max_retries: int = 2

    def __init__(self, db: Session, gateway: AIGatewayService | None = None):
        self.db = db
        self.gateway = gateway or AIGatewayService(db)
        self.prompt_svc = PromptVersionService(db)
        self.knowledge_svc = KnowledgeVersionService(db)

    def validate_input(self, context: dict[str, Any]) -> None:
        if not isinstance(context, dict):
            raise AgentValidationError("سياق الوكيل يجب أن يكون كائناً.")

    @abstractmethod
    def build_prompt(self, context: dict[str, Any]) -> tuple[str, str]:
        """يعيد (system_prompt, user_prompt)."""

    def execute(
        self,
        context: dict[str, Any],
        *,
        run_id: int | None = None,
    ) -> GatewayResult:
        system_prompt, user_prompt = self.build_prompt(context)
        return self.gateway.send_request(
            agent_name=self.agent_key,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=self.model_name or None,
            parameters=context.get("parameters"),
            run_id=run_id,
            timeout=float(self.timeout_seconds),
            prompt_version=self.prompt_version or None,
            max_retries_override=self.max_retries,
        )

    def validate_output(self, gateway_result: GatewayResult) -> StructuredAgentOutput:
        if not gateway_result.success:
            raise AgentOutputValidationError(gateway_result.error or "فشل استدعاء النموذج.")
        return StructuredAgentOutput(
            agent_key=self.agent_key,
            agent_version=self.version,
            status="success",
            data={"content": gateway_result.content},
            metadata={
                "model": gateway_result.model,
                "prompt_version": self.prompt_version,
                "knowledge_version": self.knowledge_version,
                "duration_ms": gateway_result.duration_ms,
            },
        )

    def handle_error(self, exc: Exception) -> StructuredAgentOutput:
        logger.warning("agent_error key=%s err=%s", self.agent_key, exc)
        msg = getattr(exc, "user_message", None) or str(exc)
        code = getattr(exc, "error_code", None) or "agent_execution_error"
        return StructuredAgentOutput(
            agent_key=self.agent_key,
            agent_version=self.version,
            status="failed",
            errors=[{"code": code, "message": msg}],
            metadata={
                "model": self.model_name,
                "prompt_version": self.prompt_version,
                "knowledge_version": self.knowledge_version,
                "duration_ms": 0,
            },
        )

    def run(self, context: dict[str, Any] | None = None, *, run_id: int | None = None) -> StructuredAgentOutput:
        ctx = dict(context or {})
        if not self.enabled:
            raise AgentDisabledError(f"الوكيل معطّل: {self.agent_key}")
        try:
            self.validate_input(ctx)
            gw = self.execute(ctx, run_id=run_id)
            return self.validate_output(gw)
        except (AgentDisabledError, AgentValidationError):
            raise
        except Exception as exc:  # noqa: BLE001
            if isinstance(exc, (AgentOutputValidationError, AgentExecutionError)):
                return self.handle_error(exc)
            return self.handle_error(AgentExecutionError(str(exc)))

    def apply_registry_row(self, row: Any) -> None:
        """مزامنة الحقول من صف ai_agents."""
        if row is None:
            return
        self.agent_key = row.agent_key
        self.name = row.display_name or self.name
        self.description = row.description or self.description
        self.version = row.version or self.version
        self.enabled = bool(row.enabled)
        self.model_name = row.model_name or self.model_name
        self.timeout_seconds = int(row.default_timeout_seconds or self.timeout_seconds)
        self.max_retries = int(row.max_retries if row.max_retries is not None else self.max_retries)
        if row.prompt_version_id:
            pv = self.prompt_svc.get_by_id(row.prompt_version_id)
            if pv:
                self.prompt_version = pv.version
        kv = self.knowledge_svc.get_active()
        if kv:
            self.knowledge_version = kv.version
