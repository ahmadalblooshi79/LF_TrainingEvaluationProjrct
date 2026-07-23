"""مسارات تخزين مكتبة التقارير."""

from __future__ import annotations

import os
from pathlib import Path

from app.paths import data_dir, ensure_data_directories


def ai_reports_root() -> Path:
    explicit = (os.getenv("AI_REPORTS_DIR") or "").strip()
    if explicit:
        root = Path(explicit).expanduser().resolve()
    else:
        root = (data_dir() / "instance" / "ai_reports").resolve()
    for sub in ("originals", "extracted", "failed", "archived", "temp"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    return root


def report_original_dir(public_id: str) -> Path:
    d = ai_reports_root() / "originals" / public_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def report_extracted_dir(public_id: str) -> Path:
    d = ai_reports_root() / "extracted" / public_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def report_archived_dir(public_id: str) -> Path:
    d = ai_reports_root() / "archived" / public_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def ensure_ai_report_dirs() -> None:
    ensure_data_directories(data_dir())
    ai_reports_root()
