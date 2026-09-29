# -*- coding: utf-8 -*-
from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from app.paths import data_dir, ensure_data_directories


def recovery_root() -> Path:
    root = data_dir()
    ensure_data_directories(root)
    base = root / "instance" / "tablet_recovery"
    for sub in ("originals", "staging", "reports"):
        (base / sub).mkdir(parents=True, exist_ok=True)
    return base


def ensure_recovery_dirs() -> Path:
    return recovery_root()


def archive_original_zip(src: Path, *, package_hash: str, original_name: str) -> Path:
    """حفظ نسخة ثابتة من ZIP في originals/ — لا تُعدَّل."""
    root = ensure_recovery_dirs()
    safe_name = Path(original_name or "package.zip").name
    safe_name = "".join(c if c.isalnum() or c in "._-" else "_" for c in safe_name)
    if not safe_name.lower().endswith(".zip"):
        safe_name += ".zip"
    dest = root / "originals" / f"{package_hash[:16]}_{safe_name}"
    if not dest.exists():
        shutil.copy2(src, dest)
    return dest


def new_staging_dir() -> Path:
    root = ensure_recovery_dirs()
    staging = root / "staging" / uuid.uuid4().hex
    staging.mkdir(parents=True, exist_ok=True)
    return staging
