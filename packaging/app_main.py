"""تشغيل الإنتاج على السيرفر (Waitress) — يقبل اتصالات LAN / Wi‑Fi.

يُشغَّل عبر: packaging\\start_server.bat
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("LF_INSTALL_MODE", "1")
os.environ.setdefault("FLASK_DEBUG", "0")
os.environ.setdefault("LF_OPEN_BROWSER", "1")

from waitress import serve

from app import create_app
from app.network_util import print_server_access_info

PORT = int(os.environ.get("PORT", "8005"))
HOST = os.environ.get("HOST", "0.0.0.0")

app = create_app()
print_server_access_info(host=HOST, port=PORT)

if os.environ.get("LF_OPEN_BROWSER", "1").strip().lower() not in ("0", "false", "no"):
    import threading
    import time
    import webbrowser

    def _open_local() -> None:
        time.sleep(1.2)
        webbrowser.open(f"http://127.0.0.1:{PORT}/")

    threading.Thread(target=_open_local, daemon=True).start()

serve(app, host=HOST, port=PORT, threads=int(os.environ.get("WAITRESS_THREADS", "8")))
