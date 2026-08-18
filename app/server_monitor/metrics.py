"""مقاييس الخادم والشبكة لصفحة إدارة الخادم."""

from __future__ import annotations

import os
import platform
import socket
import sys
import time
from datetime import datetime, timezone

from app.network_util import network_details, primary_lan_ipv4, primary_network_adapter
from app.server_runtime import get_listen_port

_SERVER_START_TS = time.time()


def server_uptime_seconds() -> int:
    return int(time.time() - _SERVER_START_TS)


def server_started_at_iso() -> str:
    return datetime.fromtimestamp(_SERVER_START_TS, tz=timezone.utc).isoformat()


def is_server_running() -> bool:
    return True


def hostname() -> str:
    try:
        return socket.gethostname()
    except OSError:
        return "unknown"


def listen_port() -> int:
    return get_listen_port()


def listen_host() -> str:
    return os.environ.get("HOST", "0.0.0.0")


def database_status() -> dict:
    try:
        from app.database import engine

        with engine.connect() as conn:
            conn.execute(__import__("sqlalchemy").text("SELECT 1"))
        return {"ok": True, "label": "متصل"}
    except Exception as exc:
        return {"ok": False, "label": f"خطأ: {exc}"}


def system_metrics() -> dict:
    cpu = ram = disk = None
    try:
        import psutil  # type: ignore

        cpu = round(psutil.cpu_percent(interval=0.2), 1)
        mem = psutil.virtual_memory()
        ram = round(mem.percent, 1)
        disk = round(psutil.disk_usage(os.path.splitdrive(os.getcwd())[0] or "C:").percent, 1)
    except Exception:
        pass
    return {
        "cpu_percent": cpu,
        "ram_percent": ram,
        "disk_percent": disk,
        "platform": platform.platform(),
        "python": sys.version.split()[0],
    }


def server_status_payload() -> dict:
    port = listen_port()
    ip = primary_lan_ipv4()
    net = network_details()
    adapter = primary_network_adapter() or {}
    return {
        "running": is_server_running(),
        "uptime_seconds": server_uptime_seconds(),
        "started_at": server_started_at_iso(),
        "hostname": hostname(),
        "local_ip": ip,
        "port": port,
        "connection_type": net.get("connection_type") or adapter.get("connection_type", "Unknown"),
        "access_url": f"http://{ip}:{port}/",
        "database": database_status(),
        "network": net,
        "system": system_metrics(),
    }
