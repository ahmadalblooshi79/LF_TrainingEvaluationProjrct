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

# قراءة المنفذ قبل تحميل التطبيق (load_dotenv في config قد يضبط PORT=8005).
_PREFERRED_PORT = int(os.environ.get("PORT", "8005"))
PORT = _PREFERRED_PORT
HOST = os.environ.get("HOST", "0.0.0.0")


def _app_url(port: int | None = None) -> str:
    return f"http://127.0.0.1:{int(port if port is not None else PORT)}/"


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
    url = _app_url()
    chrome = _chrome_exe()
    if chrome:
        subprocess.Popen([chrome, url], close_fds=False)
    else:
        webbrowser.open(url)


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


def _pids_listening_on_port(port: int) -> set[int]:
    """معرّفات العمليات التي تستمع على المنفذ (Windows: netstat -ano)."""
    pids: set[int] = set()
    if sys.platform == "win32":
        try:
            out = subprocess.check_output(
                ["netstat", "-ano"],
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            needle = f":{int(port)}"
            for line in out.splitlines():
                if needle not in line or "LISTENING" not in line.upper():
                    continue
                parts = line.split()
                if not parts:
                    continue
                try:
                    pid = int(parts[-1])
                except (TypeError, ValueError):
                    continue
                if pid > 0:
                    pids.add(pid)
        except (OSError, subprocess.SubprocessError, ValueError):
            pass
        return pids
    try:
        import socket

        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind(("127.0.0.1", int(port)))
        probe.close()
    except OSError:
        pass
    return pids


def _stop_other_listeners_on_port(port: int) -> None:
    """إيقاف نسخ قديمة من الخادم على نفس المنفذ (سبب شائع لـ 500 / SQLite lock)."""
    my_pid = os.getpid()
    for pid in sorted(_pids_listening_on_port(port)):
        if pid == my_pid:
            continue
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/F", "/PID", str(pid)],
                capture_output=True,
                check=False,
            )
        else:
            try:
                os.kill(pid, 9)
            except OSError:
                pass
    if _pids_listening_on_port(port) - {my_pid}:
        time.sleep(0.8)


def _can_bind_exclusive(port: int, host: str = "0.0.0.0") -> bool:
    import socket

    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if sys.platform == "win32" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    else:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        probe.bind((host, int(port)))
        return True
    except OSError:
        return False
    finally:
        probe.close()


def _resolve_listen_port(preferred: int, host: str = "0.0.0.0") -> int:
    """منفذ للاستماع — يوقف الخوادم القديمة ويتجنّب تعارض Windows (socket شبح)."""
    for port in range(int(preferred), int(preferred) + 11):
        _stop_other_listeners_on_port(port)
        if _can_bind_exclusive(port, host):
            if port != preferred:
                print(
                    f"\n[تنبيه] المنفذ {preferred} معطّل (socket شبح أو نسخة قديمة).\n"
                    f"  يعمل الخادم على المنفذ {port}: {_app_url(port)}\n",
                    file=sys.stderr,
                )
            return port
    print(
        f"\n[خطأ] لا يوجد منفذ متاح بين {preferred} و{preferred + 10}.\n"
        f"  أعد تشغيل Windows أو عيّن PORT يدوياً.\n",
        file=sys.stderr,
    )
    sys.exit(1)


def _ensure_port_free(port: int, host: str = "0.0.0.0") -> None:
    """توافق — يُستدعى _resolve_listen_port من main."""
    if not _can_bind_exclusive(port, host):
        print(
            f"\n[خطأ] المنفذ {port} ما زال مستخدماً.\n"
            f"  ثم شغّل: .venv\\Scripts\\python.exe run.py\n",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    PORT = _resolve_listen_port(_PREFERRED_PORT, HOST)
    from app.server_runtime import set_listen_port

    set_listen_port(PORT)
    from app import create_app
    from app.network_util import print_server_access_info

    app = create_app()
    debug = _env_flag("FLASK_DEBUG", default=False)
    if not str(sys.executable).lower().endswith(
        (r".venv\scripts\python.exe", r"/.venv/bin/python")
    ):
        print(
            f"\n[تحذير] المفسّر الحالي ليس .venv:\n  {sys.executable}\n"
            f"  يُفضّل: .venv\\Scripts\\python.exe run.py\n",
            file=sys.stderr,
        )
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