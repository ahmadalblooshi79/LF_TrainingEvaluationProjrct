"""الواجهة الموحدة لمزودي الذكاء الاصطناعي المحلي."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from app.ai_local_engine.schemas.request_schema import GenerateTextRequest
from app.ai_local_engine.schemas.response_schema import UnifiedAIResponse


class BaseAIProvider(ABC):
    provider_name: str = "base"

    def __init__(self, *, base_url: str, timeout: float = 300.0, retry_count: int = 2):
        self.base_url = (base_url or "").rstrip("/")
        self.timeout = float(timeout)
        self.retry_count = max(0, int(retry_count))

    @abstractmethod
    def test_connection(self) -> UnifiedAIResponse:
        ...

    @abstractmethod
    def list_models(self) -> list[dict[str, Any]]:
        ...

    @abstractmethod
    def generate_text(self, request: GenerateTextRequest) -> UnifiedAIResponse:
        ...

    @abstractmethod
    def generate_structured_output(self, request: GenerateTextRequest) -> UnifiedAIResponse:
        ...

    @abstractmethod
    def get_model_info(self, model_name: str) -> dict[str, Any]:
        ...

    @abstractmethod
    def health_check(self, model_name: str | None = None) -> dict[str, Any]:
        ...
