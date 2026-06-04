"""تشغيل الخادم من مجلد المشروع:

  run.bat
  أو: .venv\\Scripts\\python.exe run.py
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


def _ensure_port_free(port: int, host: str = "0.0.0.0") -> None:
    """إيقاف التشغيل إذا كان المنفذ مشغولاً (غالباً نسخة قديمة من python خارج .venv)."""
    import socket

    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        probe.bind((host, port))
    except OSError:
        print(
            f"\n[خطأ] المنفذ {port} مستخدم بالفعل.\n"
            f"  أوقف العملية القديمة (Task Manager أو: "
            f'Get-NetTCPConnection -LocalPort {port} | %% {{ Stop-Process -Id $_.OwningProcess -Force }})\n'
            f"  ثم شغّل: .venv\\Scripts\\python.exe run.py\n",
            file=sys.stderr,
        )
        sys.exit(1)
    finally:
        probe.close()


if __name__ == "__main__":
    _ensure_port_free(PORT, HOST)
    app = create_app()
    debug = _env_flag("FLASK_DEBUG", default=False)
    open_browser = _env_flag("LF_OPEN_BROWSER", default=True)
    # إعادة التحميل التلقائي قد تشغّل مفسّراً غير .venv على Windows (صفحة 500 / كود قديم).
    use_reloader = (
        _env_flag("FLASK_USE_RELOADER", default=False)
        and debug
        and "debugpy" not in sys.modules
    )
    app.config["TEMPLATES_AUTO_RELOAD"] = True
    if open_browser:
        _schedule_browser_open(use_reloader=use_reloader)
    print(f"  Python: {sys.executable}", flush=True)
    print_server_access_info(host=HOST, port=PORT)
    app.run(host=HOST, port=PORT, debug=debug, use_reloader=use_reloader)