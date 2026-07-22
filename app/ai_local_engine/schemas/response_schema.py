"""مخططات الاستجابة الموحدة."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from app.ai_local_engine.timing import format_duration_ms


@dataclass
class UnifiedAIResponse:
    success: bool
    text: str = ""
    provider: str = ""
    model: str = ""
    # الزمن الخام بالمللي ثانية (مصدر الحقيقة للعرض والحفظ)
    response_time_ms: int = 0
    # ثوانٍ مشتقة للتوافق مع الاستدعاءات القديمة
    response_time: float = 0.0
    error_code: str | None = None
    error_message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    timing_start: str | None = None
    timing_end: str | None = None
    raw_response: Any = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.response_time_ms and not self.response_time:
            self.response_time = self.response_time_ms / 1000.0
        elif self.response_time and not self.response_time_ms:
            self.response_time_ms = int(round(self.response_time * 1000.0))

    @property
    def response_time_display(self) -> str:
        return format_duration_ms(self.response_time_ms)

    def timing_debug(self) -> dict[str, Any]:
        return {
            "start_time": self.timing_start,
            "end_time": self.timing_end,
            "raw_milliseconds": int(self.response_time_ms or 0),
        }

    def to_public_dict(self) -> dict[str, Any]:
        meta = dict(self.metadata or {})
        meta["timing"] = self.timing_debug()
        return {
            "success": self.success,
            "text": self.text,
            "provider": self.provider,
            "model": self.model,
            "response_time_ms": int(self.response_time_ms or 0),
            "response_time": self.response_time_ms / 1000.0,
            "response_time_display": self.response_time_display,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "metadata": meta,
            "timing": self.timing_debug(),
        }


@dataclass
class HealthStatus:
    ai_enabled: bool = False
    provider: str = ""
    server_reachable: bool = False
    model_available: bool = False
    model_responding: bool = False
    response_time: float | None = None
    response_time_ms: int | None = None
    last_checked_at: str | None = None
    last_error: str | None = None
    model_name: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["response_time_display"] = format_duration_ms(self.response_time_ms)
        return d


@dataclass
class AISettingsDTO:
    enabled: bool = False
    provider: str = "ollama"
    base_url: str = "http://127.0.0.1:11434"
    model_name: str = ""
    temperature: float = 0.2
    max_tokens: int = 4096
    timeout_seconds: int = 300
    retry_count: int = 2
    context_window: int = 8192
    response_language: str = "ar"
    structured_output: bool = True
    allow_internal_network: bool = False
    allow_internet: bool = False
    telemetry: bool = False
    log_prompts: bool = False
    log_responses: bool = False
    last_connection_ok: bool | None = None
    last_connection_at: str | None = None
    last_response_ms: int | None = None
    last_error: str | None = None

    @property
    def last_response_display(self) -> str:
        return format_duration_ms(self.last_response_ms)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["last_response_display"] = self.last_response_display
        return d
