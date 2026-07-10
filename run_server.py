"""سيرفر الإنتاج — منفصل عن run.py (التطوير).

يستمع على 0.0.0.0 للوصول عبر Ethernet و Wi‑Fi من أجهزة الشبكة المحلية.
البيانات في %%LOCALAPPDATA%%\\LF_TrainingEvaluation\\
"""
from __future__ import annotations

import os
import sys

# قبل تحميل التطبيق — وضع التثبيت + شبكة LAN
os.environ.setdefault("LF_INSTALLED", "1")
os.environ.setdefault("HOST", "0.0.0.0")
os.environ.setdefault("LF_OPEN_BROWSER", "0")
os.environ.setdefault("LF_SERVER_BANNER", "1")
os.environ.setdefault("FLASK_DEBUG", "0")
os.environ.setdefault("FLASK_USE_RELOADER", "0")

if getattr(sys, "frozen", False):
    os.environ.setdefault("LF_INSTALLED", "1")

from run import main

if __name__ == "__main__":
    main()
