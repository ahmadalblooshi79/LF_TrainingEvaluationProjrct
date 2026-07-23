"""هيكل مبدئي لمزود LM Studio (مرحلة لاحقة)."""

from __future__ import annotations

from typing import Any

from app.ai_local_engine.exceptions import AIProviderNotImplementedError
from app.ai_local_engine.providers.base_provider import BaseAIProvider
from app.ai_local_engine.schemas.request_schema import GenerateTextRequest
from app.ai_local_engine.schemas.response_schema import UnifiedAIResponse


class LMStudioProvider(BaseAIProvider):
    provider_name = "lmstudio"

    def __init__(self, *, base_url: str = "http://127.0.0.1:1234", timeout: float = 300.0, retry_count: int = 2):
        super().__init__(base_url=base_url or "http://127.0.0.1:1234", timeout=timeout, retry_count=retry_count)

    def test_connection(self) -> UnifiedAIResponse:
        return UnifiedAIResponse(
            success=False,
            provider=self.provider_name,
            error_code="provider_not_ready",
            error_message=AIProviderNotImplementedError.user_message,
            metadata={"base_url": self.base_url, "phase": 1, "stub": True},
        )

    def list_models(self) -> list[dict[str, Any]]:
        raise AIProviderNotImplementedError()

    def generate_text(self, request: GenerateTextRequest) -> UnifiedAIResponse:
        return self.test_connection()

    def generate_structured_output(self, request: GenerateTextRequest) -> UnifiedAIResponse:
        return self.test_connection()

    def get_model_info(self, model_name: str) -> dict[str, Any]:
        raise AIProviderNotImplementedError()

    def health_check(self, model_name: str | None = None) -> dict[str, Any]:
        return {
            "server_reachable": False,
            "model_available": False,
            "model_responding": False,
            "response_time": None,
            "last_error": AIProviderNotImplementedError.user_message,
            "provider": self.provider_name,
            "stub": True,
        }
