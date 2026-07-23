"""إعدادات المحرك المحلي من البيئة (قيم افتراضية آمنة)."""

from __future__ import annotations

import os


def _bool_env(name: str, default: bool) -> bool:
    raw = (os.getenv(name) or "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def _float_env(name: str, default: float) -> float:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _int_env(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


# افتراضيات آمنة: لا إنترنت، لا telemetry، لا تسجيل prompts/responses
AI_ENABLED = _bool_env("AI_ENABLED", True)
AI_PROVIDER = (os.getenv("AI_PROVIDER") or "ollama").strip().lower() or "ollama"
AI_BASE_URL = (os.getenv("AI_BASE_URL") or "http://127.0.0.1:11434").strip()
AI_MODEL_NAME = (os.getenv("AI_MODEL_NAME") or "").strip()
AI_TEMPERATURE = _float_env("AI_TEMPERATURE", 0.2)
AI_MAX_TOKENS = _int_env("AI_MAX_TOKENS", 4096)
AI_TIMEOUT_SECONDS = _int_env("AI_TIMEOUT_SECONDS", 300)
AI_RETRY_COUNT = _int_env("AI_RETRY_COUNT", 2)
AI_CONTEXT_WINDOW = _int_env("AI_CONTEXT_WINDOW", 8192)
AI_RESPONSE_LANGUAGE = (os.getenv("AI_RESPONSE_LANGUAGE") or "ar").strip() or "ar"
AI_STRUCTURED_OUTPUT = _bool_env("AI_STRUCTURED_OUTPUT", True)
AI_ALLOW_INTERNET = _bool_env("AI_ALLOW_INTERNET", False)
AI_ALLOW_INTERNAL_NETWORK = _bool_env("AI_ALLOW_INTERNAL_NETWORK", False)
AI_TELEMETRY = _bool_env("AI_TELEMETRY", False)
AI_LOG_PROMPTS = _bool_env("AI_LOG_PROMPTS", False)
AI_LOG_RESPONSES = _bool_env("AI_LOG_RESPONSES", False)

# وضع المحرك: legacy | agentic | hybrid (القيمة الافتراضية hybrid)
_AI_ENGINE_MODE_RAW = (os.getenv("AI_ENGINE_MODE") or "hybrid").strip().lower()
AI_ENGINE_MODE = _AI_ENGINE_MODE_RAW if _AI_ENGINE_MODE_RAW in ("legacy", "agentic", "hybrid") else "hybrid"
AI_AGENTIC_ENABLED = _bool_env("AI_AGENTIC_ENABLED", True)
AI_DEFAULT_MODEL = (os.getenv("AI_DEFAULT_MODEL") or AI_MODEL_NAME or "").strip()
AI_DEFAULT_TIMEOUT = _int_env("AI_DEFAULT_TIMEOUT", AI_TIMEOUT_SECONDS)
AI_DEFAULT_MAX_RETRIES = _int_env("AI_DEFAULT_MAX_RETRIES", AI_RETRY_COUNT)
AI_SAVE_RAW_RESPONSES = _bool_env("AI_SAVE_RAW_RESPONSES", False)

ALLOWED_PROVIDERS = frozenset({"ollama", "lmstudio", "llamacpp"})
MAX_TEST_PROMPT_CHARS = 2000
