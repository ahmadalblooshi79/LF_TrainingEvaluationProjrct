"""إضافة جذر المشروع إلى sys.path (للتشغيل عبر run.py أو عند فتح ملف داخل app/ مباشرة)."""
from __future__ import annotations

import sys
from pathlib import Path


def ensure() -> Path:
    root = Path(__file__).resolve().parent
    s = str(root)
    if s not in sys.path:
        sys.path.insert(0, s)
    return root


ensure()
