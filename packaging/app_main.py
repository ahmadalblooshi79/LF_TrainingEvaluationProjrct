"""تشغيل الإنتاج على السيرفر (Waitress) — يقبل اتصالات LAN / Wi‑Fi.

يُشغَّل عبر: START_SERVER.bat أو packaging\\start_server.bat
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# تحميل .env قبل ضبط الافتراضيات
from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

os.environ.setdefault("LF_INSTALL_MODE", "1")
os.environ.setdefault("FLASK_DEBUG", "0")
os.environ.setdefault("LF_OPEN_BROWSER", "1")
os.environ.setdefault("HOST", "0.0.0.0")
os.environ.setdefault("PORT", "8005")
os.environ.setdefault("WAITRESS_THREADS", "16")

from waitress import serve

from app import create_app
from app.network_util import print_server_access_info

PORT = int(os.environ.get("PORT", "8005"))
HOST = os.environ.get("HOST", "0.0.0.0")
THREADS = int(os.environ.get("WAITRESS_THREADS", "16"))
CHANNEL_TIMEOUT = int(os.environ.get("WAITRESS_CHANNEL_TIMEOUT", "120"))
CONNECTION_LIMIT = int(os.environ.get("WAITRESS_CONNECTION_LIMIT", "200"))

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

serve(
    app,
    host=HOST,
    port=PORT,
    threads=THREADS,
    channel_timeout=CHANNEL_TIMEOUT,
    connection_limit=CONNECTION_LIMIT,
    asyncore_use_poll=True,
)
