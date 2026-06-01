"""تشغيل الخادم من مجلد المشروع (تطوير):

  run.bat
  أو: .venv\\Scripts\\python.exe run.py

تنصيب السيرفر للإنتاج + LAN/Wi‑Fi: INSTALL.bat ثم START_SERVER.bat
"""
import os
import shutil
import subprocess
import sys
import threading
import time
import webbrowser

from app import create_app
from app.network_util import print_server_access_info

# منفذ ثابت للتطبيق حتى لا تتكرر مشكلة اختلاف الرابط بين 8003/8004/8005.
PORT = int(os.environ.get("PORT", "8005"))
HOST = os.environ.get("HOST", "0.0.0.0")
APP_URL = f"http://127.0.0.1:{PORT}/"


def _chrome_exe() -> str | None:
    for var in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        base = os.environ.get(var)
        if not base:
            continue
        path = os.path.join(base, "Google", "Chrome", "Application", "chrome.exe")
        if os.path.isfile(path):
            return path
    which = shutil.which("chrome")
    return which if which and os.path.isfile(which) else None


def _open_browser() -> None:
    time.sleep(1.0)
    chrome = _chrome_exe()
    if chrome:
        subprocess.Popen([chrome, APP_URL], close_fds=False)
    else:
        webbrowser.open(APP_URL)


_BROWSER_OPEN_SCHEDULED = False


def _schedule_browser_open(*, use_reloader: bool) -> None:
    """فتح المتصفح مرة واحدة فقط (تجنّب تكرار الفتح مع werkzeug reloader)."""
    global _BROWSER_OPEN_SCHEDULED
    if use_reloader and os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        return
    if _BROWSER_OPEN_SCHEDULED:
        return
    _BROWSER_OPEN_SCHEDULED = True
    threading.Thread(target=_open_browser, daemon=True).start()


def _env_flag(name: str, default: bool = True) -> bool:
    v = (os.environ.get(name) or "").strip().lower()
    if not v:
        return default
    return v not in ("0", "false", "no", "off")


if __name__ == "__main__":
    app = create_app()
    debug = _env_flag("FLASK_DEBUG", default=True)
    open_browser = _env_flag("LF_OPEN_BROWSER", default=True)
    use_reloader = debug and "debugpy" not in sys.modules
    if open_browser:
        _schedule_browser_open(use_reloader=use_reloader)
    print_server_access_info(host=HOST, port=PORT)
    app.run(host=HOST, port=PORT, debug=debug, use_reloader=use_reloader)