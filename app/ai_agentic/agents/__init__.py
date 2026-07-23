"""مصنع الوكلاء المسجّلين في الكود."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.ai_agentic.agents.system_health_agent import SystemHealthAgent
from app.ai_agentic.constants import SYSTEM_HEALTH_AGENT_KEY
from app.ai_agentic.exceptions import AgentValidationError

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from app.ai_agentic.agents.base_agent import BaseAgent
    from app.ai_agentic.services.ai_gateway_service import AIGatewayService


_CODE_AGENTS = {
    SYSTEM_HEALTH_AGENT_KEY: SystemHealthAgent,
}


def create_agent_instance(
    agent_key: str,
    db: "Session",
    gateway: "AIGatewayService | None" = None,
) -> "BaseAgent":
    cls = _CODE_AGENTS.get(agent_key)
    if not cls:
        raise AgentValidationError(f"لا يوجد تنفيذ برمجي للوكيل: {agent_key}")
    return cls(db, gateway=gateway)
