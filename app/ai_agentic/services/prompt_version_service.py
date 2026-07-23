"""إدارة إصدارات الـ Prompt والمعرفة."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.ai_agentic.models import AiKnowledgeVersion, AiPromptVersion


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class PromptVersionService:
    def __init__(self, db: Session):
        self.db = db

    def get_active_for_agent(self, agent_key: str) -> AiPromptVersion | None:
        return (
            self.db.query(AiPromptVersion)
            .filter(
                AiPromptVersion.agent_key == agent_key,
                AiPromptVersion.is_active.is_(True),
            )
            .order_by(AiPromptVersion.id.desc())
            .first()
        )

    def get_by_id(self, prompt_id: int) -> AiPromptVersion | None:
        return self.db.get(AiPromptVersion, prompt_id)

    def get(self, prompt_key: str, version: str) -> AiPromptVersion | None:
        return (
            self.db.query(AiPromptVersion)
            .filter(
                AiPromptVersion.prompt_key == prompt_key,
                AiPromptVersion.version == version,
            )
            .first()
        )


class KnowledgeVersionService:
    def __init__(self, db: Session):
        self.db = db

    def get_active(self) -> AiKnowledgeVersion | None:
        return (
            self.db.query(AiKnowledgeVersion)
            .filter(AiKnowledgeVersion.status == "active")
            .order_by(AiKnowledgeVersion.id.desc())
            .first()
        )

    def get(self, version: str) -> AiKnowledgeVersion | None:
        return (
            self.db.query(AiKnowledgeVersion)
            .filter(AiKnowledgeVersion.version == version)
            .first()
        )
