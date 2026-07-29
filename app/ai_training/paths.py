"""مسارات تخزين وثائق التدريب."""

from __future__ import annotations

from pathlib import Path

from app.ai_training import config as cfg
from app.paths import data_dir, ensure_data_directories


def ai_training_root() -> Path:
    if cfg.AI_TRAINING_STORAGE_PATH:
        root = Path(cfg.AI_TRAINING_STORAGE_PATH).expanduser().resolve()
    else:
        root = (data_dir() / "instance" / "ai_training").resolve()
    for sub in ("originals", "extracted", "previews", "temp", "failed"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    return root


def document_original_dir(document_uuid: str) -> Path:
    d = ai_training_root() / "originals" / document_uuid
    d.mkdir(parents=True, exist_ok=True)
    return d


def document_extracted_dir(document_uuid: str) -> Path:
    d = ai_training_root() / "extracted" / document_uuid
    d.mkdir(parents=True, exist_ok=True)
    return d


def document_failed_dir(document_uuid: str) -> Path:
    d = ai_training_root() / "failed" / document_uuid
    d.mkdir(parents=True, exist_ok=True)
    return d


def ensure_ai_training_dirs() -> None:
    ensure_data_directories(data_dir())
    ai_training_root()
