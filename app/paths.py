"""مسارات التطبيق: مجلد الكود مقابل مجلد البيانات (وضع التنصيب على السيرفر)."""

from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "LF_TrainingEvaluation"

# جذر المشروع (مجلد run.py)
APP_DIR = Path(__file__).resolve().parent.parent


def is_installed_mode() -> bool:
    v = (os.getenv("LF_INSTALL_MODE") or os.getenv("LF_INSTALLED") or "").strip().lower()
    return v in ("1", "true", "yes", "on")


def data_dir() -> Path:
    """مجلد قاعدة البيانات والمرفقات."""
    explicit = (os.getenv("LF_DATA_DIR") or "").strip()
    if explicit:
        return Path(explicit).expanduser().resolve()
    if is_installed_mode():
        local = os.environ.get("LOCALAPPDATA") or os.environ.get("HOME") or str(Path.home())
        return (Path(local) / APP_NAME).resolve()
    return APP_DIR.resolve()


def ensure_data_directories(root: Path) -> None:
    """إنشاء مجلدات التخزين عند أول تشغيل (سيرفر أو تطوير)."""
    subdirs = (
        "exercise_store",
        "instance/dilemma_pdfs",
        "instance/evaluation_list_xlsx",
        "instance/chat_uploads",
        "instance/visual_docs",
        "instance/eval_criterion_media",
        "instance/information_bank",
        "instance/library",
        "instance/planner_flow_bundles",
    )
    root.mkdir(parents=True, exist_ok=True)
    for rel in subdirs:
        (root / rel).mkdir(parents=True, exist_ok=True)
