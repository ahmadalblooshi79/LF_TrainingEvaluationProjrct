"""تشغيل Flask كخدمة Windows — HOST=0.0.0.0 PORT=8005."""
from __future__ import annotations

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.chdir(ROOT)
os.environ.setdefault("HOST", "0.0.0.0")
os.environ.setdefault("PORT", "8005")
os.environ.setdefault("LF_OPEN_BROWSER", "0")

from app import create_app  # noqa: E402

app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8005"))
    host = os.environ.get("HOST", "0.0.0.0")
    try:
        from waitress import serve

        serve(app, host=host, port=port, threads=8)
    except ImportError:
        app.run(host=host, port=port, debug=False, use_reloader=False)
