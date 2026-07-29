"""إعدادات تحليل البنية العسكرية (Phase B2.1)."""

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


def _float_env(name: str, default: float) -> float:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


AI_STRUCTURE_ENABLED = _bool_env("AI_STRUCTURE_ENABLED", True)
AI_STRUCTURE_MODEL = (os.getenv("AI_STRUCTURE_MODEL") or "qwen3:8b").strip()
AI_STRUCTURE_CHUNK_BLOCKS = _int_env("AI_STRUCTURE_CHUNK_BLOCKS", 40)
AI_STRUCTURE_CONTEXT_BEFORE = _int_env("AI_STRUCTURE_CONTEXT_BEFORE", 3)
AI_STRUCTURE_CONTEXT_AFTER = _int_env("AI_STRUCTURE_CONTEXT_AFTER", 3)
AI_STRUCTURE_MAX_CHARACTERS = _int_env("AI_STRUCTURE_MAX_CHARACTERS", 12000)
AI_STRUCTURE_TIMEOUT_SECONDS = _int_env("AI_STRUCTURE_TIMEOUT_SECONDS", 120)
AI_STRUCTURE_MAX_RETRIES = _int_env("AI_STRUCTURE_MAX_RETRIES", 2)
AI_STRUCTURE_RULES_ENABLED = _bool_env("AI_STRUCTURE_RULES_ENABLED", True)
AI_STRUCTURE_LLM_ENABLED = _bool_env("AI_STRUCTURE_LLM_ENABLED", True)
AI_STRUCTURE_CONFIDENCE_HIGH = _float_env("AI_STRUCTURE_CONFIDENCE_HIGH", 0.85)
AI_STRUCTURE_CONFIDENCE_MEDIUM = _float_env("AI_STRUCTURE_CONFIDENCE_MEDIUM", 0.60)
AI_STRUCTURE_AUTO_RUN = _bool_env("AI_STRUCTURE_AUTO_RUN", False)
AI_STRUCTURE_SAVE_LLM_RAW_RESPONSE = _bool_env("AI_STRUCTURE_SAVE_LLM_RAW_RESPONSE", False)
