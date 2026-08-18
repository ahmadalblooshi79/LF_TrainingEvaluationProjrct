"""تشغيل الخادم من مجلد المشروع:

  run.bat
  أو: .venv\\Scripts\\python.exe run.py
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import threading
import time
import webbrowser

_ROOT = os.path.dirname(os.path.abspath(__file__))


def _preferred_port() -> int:
    raw = (os.environ.get("PORT") or "8005").strip()
    try:
        return int(raw)
    except ValueError:
        return 8005


def _ensure_project_root() -> None:
    """ثبّت cwd وsys.path على جذر المشروع (زر التشغيل قد يغيّر المجلد)."""
    if os.getcwd() != _ROOT:
        os.chdir(_ROOT)
    if _ROOT not in sys.path:
        sys.path.insert(0, _ROOT)


def _venv_python() -> str | None:
    if sys.platform == "win32":
        candidate = os.path.join(_ROOT, ".venv", "Scripts", "python.exe")
    else:
        candidate = os.path.join(_ROOT, ".venv", "bin", "python")
    return candidate if os.path.isfile(candidate) else None


def _is_same_python(a: str, b: str) -> bool:
    try:
        return os.path.samefile(a, b)
    except OSError:
        return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def _reexec_under_venv_if_needed() -> None:
    """أعِد التشغيل عبر .venv عندما يضغط المستخدم Play بمفسّر النظام."""
    if getattr(sys, "frozen", False):
        return
    if os.environ.get("LF_VENV_REEXEC") == "1":
        return
    venv_py = _venv_python()
    if not venv_py:
        return
    if _is_same_python(sys.executable, venv_py):
        return
    exe_l = str(sys.executable).replace("/", "\\").lower()
    if exe_l.endswith(r".venv\scripts\python.exe") or exe_l.endswith("/.venv/bin/python"):
        return
    os.environ["LF_VENV_REEXEC"] = "1"
    script = os.path.abspath(sys.argv[0])
    print(
        f"[INFO] Switching to project venv:\n  {venv_py}\n"
        f"  (was: {sys.executable})",
        flush=True,
    )
    # os.execv غير موثوق على Windows (يخرج الأب فوراً فيبدو أن زر التشغيل لا يعمل).
    if sys.platform == "win32":
        raise SystemExit(
            subprocess.call([venv_py, script, *sys.argv[1:]], cwd=_ROOT)
        )
    os.execv(venv_py, [venv_py, script, *sys.argv[1:]])


_ensure_project_root()

# قراءة المنفذ قبل تحميل التطبيق (load_dotenv في config قد يضبط PORT=8005).
_PREFERRED_PORT = _preferred_port()
PORT = _PREFERRED_PORT
HOST = (os.environ.get("HOST") or "0.0.0.0").strip() or "0.0.0.0"


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


_WIN_LISTEN_RE = re.compile(
    r"^\s*TCP\s+(\S+):(\d+)\s+\S+\s+LISTENING\s+(\d+)\s*$",
    re.IGNORECASE,
)


def _pids_listening_on_port(port: int) -> set[int]:
    """معرّفات العمليات التي تستمع على المنفذ (Windows: netstat -ano)."""
    pids: set[int] = set()
    want = int(port)
    if sys.platform == "win32":
        try:
            out = subprocess.check_output(
                ["netstat", "-ano"],
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            for line in out.splitlines():
                m = _WIN_LISTEN_RE.match(line)
                if not m:
                    continue
                if int(m.group(2)) != want:
                    continue
                pid = int(m.group(3))
                if pid > 0:
                    pids.add(pid)
        except (OSError, subprocess.SubprocessError, ValueError):
            pass
        return pids
    try:
        import socket

        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind(("127.0.0.1", want))
        probe.close()
    except OSError:
        pass
    return pids


def _stop_other_listeners_on_port(port: int) -> None:
    """إيقاف نسخ قديمة من الخادم على نفس المنفذ (سبب شائع لـ 500 / SQLite lock)."""
    my_pid = os.getpid()
    parent = os.getppid()
    killed = False
    for pid in sorted(_pids_listening_on_port(port)):
        if pid in (my_pid, parent):
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
        killed = True
    if killed:
        for _ in range(10):
            leftover = _pids_listening_on_port(port) - {my_pid, parent}
            if not leftover:
                break
            time.sleep(0.2)


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
        # بعد الإيقاف قد يبقى المنفذ لحظة قصيرة على Windows.
        for _ in range(5):
            if _can_bind_exclusive(port, host):
                if port != preferred:
                    print(
                        f"\n[warn] Port {preferred} unavailable (ghost socket or old instance).\n"
                        f"  Server listening on port {port}: {_app_url(port)}\n",
                        file=sys.stderr,
                    )
                return port
            time.sleep(0.15)
    print(
        f"\n[error] No free port between {preferred} and {preferred + 10}.\n"
        f"  Restart Windows or set PORT manually.\n",
        file=sys.stderr,
    )
    sys.exit(1)


def _ensure_port_free(port: int, host: str = "0.0.0.0") -> None:
    """توافق — يُستدعى _resolve_listen_port من main."""
    if not _can_bind_exclusive(port, host):
        print(
            f"\n[error] Port {port} is still in use.\n"
            f"  Then run: .venv\\Scripts\\python.exe run.py\n",
            file=sys.stderr,
        )
        sys.exit(1)


def main() -> None:
    global PORT
    _ensure_project_root()
    if getattr(sys, "frozen", False):
        os.environ.setdefault("LF_INSTALLED", "1")
    PORT = _resolve_listen_port(_PREFERRED_PORT, HOST)
    try:
        from app.server_runtime import set_listen_port

        set_listen_port(PORT)
        from app import create_app
        from app.network_util import print_server_access_info
    except ModuleNotFoundError as exc:
        print(
            f"\n[error] Failed to import required package: {exc}\n"
            f"  Interpreter: {sys.executable}\n"
            f"  Run: .venv\\Scripts\\python.exe run.py\n"
            f"  Or: run.bat\n",
            file=sys.stderr,
        )
        sys.exit(1)

    app = create_app()
    try:
        from app.remote_control_ws import start_remote_control_ws_server

        ws_port = PORT + 1
        if start_remote_control_ws_server(host=HOST if HOST != "127.0.0.1" else "0.0.0.0", port=ws_port):
            print(f"  Remote Control WebSocket: ws://<host>:{ws_port}/", flush=True)
        print(f"  Presentation display: http://<host>:{PORT}/presentation/live", flush=True)
    except Exception as exc:
        print(f"  [warn] Remote-control WebSocket: {exc}", flush=True)
    debug = _env_flag("FLASK_DEBUG", default=False) and not getattr(sys, "frozen", False)
    if not getattr(sys, "frozen", False) and not str(sys.executable).lower().endswith(
        (r".venv\scripts\python.exe", r"/.venv/bin/python")
    ):
        print(
            f"\n[warn] Current interpreter is not .venv:\n  {sys.executable}\n"
            f"  Prefer: .venv\\Scripts\\python.exe run.py\n",
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
    if getattr(sys, "frozen", False):
        from waitress import serve  # type: ignore[import-untyped,reportMissingModuleSource]

        serve(app, host=HOST, port=PORT, threads=8)
        return
    # threaded=True ضروري: قناة SSE لشاشة العرض تبقى مفتوحة؛ بدونها تتجمّد أوامر التحكم والتنقل.
    app.run(
        host=HOST,
        port=PORT,
        debug=debug,
        use_reloader=use_reloader,
        threaded=True,
    )


if __name__ == "__main__":
    try:
        _ensure_project_root()
        _reexec_under_venv_if_needed()
        main()
    except SystemExit:
        raise
    except Exception as exc:
        print(f"\n[error] Server failed to start: {exc}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        if sys.platform == "win32" and sys.stdin.isatty():
            try:
                input("\nPress Enter to close...")
            except EOFError:
                pass
        sys.exit(1)
