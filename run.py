"""تشغيل الخادم: python run.py"""
import os
import shutil
import subprocess
import threading
import time
import webbrowser

from app import create_app

# منفذ ثابت للتطبيق حتى لا تتكرر مشكلة اختلاف الرابط بين 8003/8004/8005.
PORT = int(os.environ.get("PORT", "8005"))
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


if __name__ == "__main__":
    app = create_app()
    threading.Thread(target=_open_browser, daemon=True).start()
    app.run(host="0.0.0.0", port=PORT, debug=True, use_reloader=False)
    