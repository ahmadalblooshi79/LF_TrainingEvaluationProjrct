"""Start the local server (if needed) and open the app in the browser."""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

DEFAULT_PORT = 8005


def _app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent.parent


def _preferred_port() -> int:
    raw = (os.environ.get("PORT") or "").strip()
    if raw.isdigit():
        return int(raw)
    return DEFAULT_PORT


def _app_url(port: int) -> str:
    return f"http://127.0.0.1:{int(port)}/"


def _port_listening(port: int, host: str = "127.0.0.1") -> bool:
    try:
        with socket.create_connection((host, int(port)), timeout=0.5):
            return True
    except OSError:
        return False


def _wait_for_port(port: int, timeout: float = 60.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _port_listening(port):
            return True
        time.sleep(0.4)
    return False


def _start_server(server_exe: Path) -> None:
    cwd = str(server_exe.parent)
    kwargs: dict = {"cwd": cwd, "close_fds": False}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    subprocess.Popen([str(server_exe)], **kwargs)


def _chrome_exe() -> str | None:
    for var in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        base = os.environ.get(var)
        if not base:
            continue
        path = Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe"
        if path.is_file():
            return str(path)
    return None


def _open_browser(url: str) -> None:
    chrome = _chrome_exe()
    if chrome:
        subprocess.Popen([chrome, url], close_fds=False)
        return
    webbrowser.open(url)


def main() -> None:
    app_dir = _app_dir()
    server_exe = app_dir / "LF_TrainingEvaluation_Server.exe"
    if not server_exe.is_file():
        print(f"Server executable not found: {server_exe}", file=sys.stderr)
        sys.exit(1)

    port = _preferred_port()
    if not _port_listening(port):
        _start_server(server_exe)
        if not _wait_for_port(port):
            print(f"Server did not respond on port {port}", file=sys.stderr)
            sys.exit(1)

    _open_browser(_app_url(port))


if __name__ == "__main__":
    main()
