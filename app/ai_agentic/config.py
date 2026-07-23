"""إعدادات Agentic Engine من البيئة (قيم افتراضية آمنة)."""

from __future__ import annotations

import os


def _bool_env(name: str, default: bool) -> bool:
    raw = (os.getenv(name) or "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def _int_env(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


# legacy | agentic | hybrid
_AI_ENGINE_MODE_RAW = (os.getenv("AI_ENGINE_MODE") or "hybrid").strip().lower()
AI_ENGINE_MODE = _AI_ENGINE_MODE_RAW if _AI_ENGINE_MODE_RAW in ("legacy", "agentic", "hybrid") else "hybrid"

AI_AGENTIC_ENABLED = _bool_env("AI_AGENTIC_ENABLED", True)
AI_DEFAULT_MODEL = (os.getenv("AI_DEFAULT_MODEL") or "").strip()
AI_DEFAULT_TIMEOUT = _int_env("AI_DEFAULT_TIMEOUT", 120)
AI_DEFAULT_MAX_RETRIES = _int_env("AI_DEFAULT_MAX_RETRIES", 2)
AI_SAVE_RAW_RESPONSES = _bool_env("AI_SAVE_RAW_RESPONSES", False)
AI_LOG_PROMPTS = _bool_env("AI_LOG_PROMPTS", False)

# مزامنة مع إعدادات المحرك المحلي إن وُجدت
try:
    from app.ai_local_engine import config as _legacy_cfg

    if not AI_DEFAULT_MODEL and getattr(_legacy_cfg, "AI_MODEL_NAME", ""):
        AI_DEFAULT_MODEL = _legacy_cfg.AI_MODEL_NAME
    # احترام AI_LOG_PROMPTS المحلي إن لم يُضبط متغير agentic صراحة
    if "AI_LOG_PROMPTS" not in os.environ and getattr(_legacy_cfg, "AI_LOG_PROMPTS", False):
        AI_LOG_PROMPTS = bool(_legacy_cfg.AI_LOG_PROMPTS)
except Exception:  # noqa: BLE001 — تحميل اختياري عند الاستيراد المبكر
    pass


def is_agentic_runtime_allowed() -> bool:
    """هل يُسمح بتشغيل Agentic Engine؟"""
    if not AI_AGENTIC_ENABLED:
        return False
    return AI_ENGINE_MODE in ("agentic", "hybrid")


def is_legacy_runtime_allowed() -> bool:
    """هل يُسمح بتشغيل Legacy Engine؟"""
    return AI_ENGINE_MODE in ("legacy", "hybrid")
