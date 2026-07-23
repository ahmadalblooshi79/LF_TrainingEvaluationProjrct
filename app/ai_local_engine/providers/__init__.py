"""مزودو النماذج المحلية."""

from app.ai_local_engine.providers.base_provider import BaseAIProvider
from app.ai_local_engine.providers.llamacpp_provider import LlamaCppProvider
from app.ai_local_engine.providers.lmstudio_provider import LMStudioProvider
from app.ai_local_engine.providers.ollama_provider import OllamaProvider

__all__ = [
    "BaseAIProvider",
    "OllamaProvider",
    "LMStudioProvider",
    "LlamaCppProvider",
    "get_provider",
]


def get_provider(name: str, *, base_url: str, timeout: float, retry_count: int = 2) -> BaseAIProvider:
    key = (name or "ollama").strip().lower()
    if key == "ollama":
        return OllamaProvider(base_url=base_url, timeout=timeout, retry_count=retry_count)
    if key in ("lmstudio", "lm_studio", "lm-studio"):
        return LMStudioProvider(base_url=base_url, timeout=timeout, retry_count=retry_count)
    if key in ("llamacpp", "llama.cpp", "llama_cpp"):
        return LlamaCppProvider(base_url=base_url, timeout=timeout, retry_count=retry_count)
    from app.ai_local_engine.exceptions import AIProviderNotConfiguredError

    raise AIProviderNotConfiguredError(f"مزود غير معروف: {name}")
