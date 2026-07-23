"""صيغة المخرجات الموحدة للوكلاء."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class StructuredAgentOutput:
    agent_key: str = ""
    agent_version: str = ""
    status: str = "success"  # success | warning | failed
    confidence: float | None = None
    data: dict[str, Any] = field(default_factory=dict)
    warnings: list[Any] = field(default_factory=list)
    errors: list[Any] = field(default_factory=list)
    sources: list[Any] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "StructuredAgentOutput":
        p = payload or {}
        return cls(
            agent_key=str(p.get("agent_key") or ""),
            agent_version=str(p.get("agent_version") or ""),
            status=str(p.get("status") or "success"),
            confidence=p.get("confidence"),
            data=dict(p.get("data") or {}),
            warnings=list(p.get("warnings") or []),
            errors=list(p.get("errors") or []),
            sources=list(p.get("sources") or []),
            metadata=dict(p.get("metadata") or {}),
        )


@dataclass
class GatewayResult:
    success: bool
    content: str = ""
    model: str = ""
    duration_ms: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
    error: str | None = None
    error_code: str | None = None
    raw_response: dict[str, Any] | None = None
    agent_name: str | None = None
    run_id: int | None = None
    prompt_version: str | None = None
    retry_count: int = 0

    def to_dict(self, *, include_raw: bool = False) -> dict[str, Any]:
        d: dict[str, Any] = {
            "success": self.success,
            "content": self.content,
            "model": self.model,
            "duration_ms": int(self.duration_ms or 0),
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "error": self.error,
            "error_code": self.error_code,
            "agent_name": self.agent_name,
            "run_id": self.run_id,
            "prompt_version": self.prompt_version,
            "retry_count": int(self.retry_count or 0),
            "raw_response": self.raw_response if include_raw else {},
        }
        return d
