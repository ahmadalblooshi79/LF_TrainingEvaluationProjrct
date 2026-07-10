"""Client launcher — opens the remote server UI in the browser (no local server)."""
from __future__ import annotations

import configparser
import os
import sys
import webbrowser
from pathlib import Path

DEFAULT_PORT = 8005


def _app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent.parent


def _load_server_target(app_dir: Path) -> tuple[str, int]:
    host = (os.environ.get("LF_SERVER_HOST") or "").strip()
    port_raw = (os.environ.get("LF_SERVER_PORT") or "").strip()
    port = int(port_raw) if port_raw.isdigit() else DEFAULT_PORT

    ini_path = app_dir / "client.ini"
    if ini_path.is_file():
        cfg = configparser.ConfigParser()
        cfg.read(ini_path, encoding="utf-8")
        if cfg.has_section("server"):
            host = (cfg.get("server", "host", fallback=host) or host).strip()
            port = cfg.getint("server", "port", fallback=port)

    return host, port


def _show_error(message: str) -> None:
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(  # type: ignore[attr-defined]
                0,
                message,
                "LF Training Evaluation",
                0x10,
            )
            return
        except OSError:
            pass
    print(message, file=sys.stderr)


def main() -> None:
    app_dir = _app_dir()
    host, port = _load_server_target(app_dir)
    if not host:
        _show_error(
            "Set the server IP in client.ini:\n\n"
            "[server]\n"
            "host=192.168.1.100\n"
            "port=8005"
        )
        sys.exit(1)

    webbrowser.open(f"http://{host}:{int(port)}/")


if __name__ == "__main__":
    main()
