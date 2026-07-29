"""إعدادات مركز التدريب من البيئة."""

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


AI_TRAINING_STORAGE_PATH = (os.getenv("AI_TRAINING_STORAGE_PATH") or "").strip()
AI_TRAINING_MAX_FILE_SIZE_MB = _int_env("AI_TRAINING_MAX_FILE_SIZE_MB", 50)
AI_TRAINING_ALLOWED_EXTENSIONS = (
    os.getenv("AI_TRAINING_ALLOWED_EXTENSIONS") or "docx,pdf,txt"
).strip().lower()
AI_TRAINING_AUTO_INGEST = _bool_env("AI_TRAINING_AUTO_INGEST", True)
AI_INGESTION_LLM_ASSISTED = _bool_env("AI_INGESTION_LLM_ASSISTED", False)
AI_INGESTION_KEEP_TEMP_FILES = _bool_env("AI_INGESTION_KEEP_TEMP_FILES", False)
AI_INGESTION_EXTRACT_HEADERS_FOOTERS = _bool_env("AI_INGESTION_EXTRACT_HEADERS_FOOTERS", True)
AI_INGESTION_EXTRACT_TABLES = _bool_env("AI_INGESTION_EXTRACT_TABLES", True)
AI_INGESTION_PDF_BLOCK_MODE = (os.getenv("AI_INGESTION_PDF_BLOCK_MODE") or "lines").strip().lower()
AI_INGESTION_DUPLICATE_POLICY = (os.getenv("AI_INGESTION_DUPLICATE_POLICY") or "warn").strip().lower()
