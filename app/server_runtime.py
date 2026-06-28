"""منفذ الاستماع الفعلي للعملية الجارية (يُضبط من run.py)."""

from __future__ import annotations

import os

_LISTEN_PORT: int | None = None


def set_listen_port(port: int) -> None:
    global _LISTEN_PORT
    _LISTEN_PORT = int(port)


def get_listen_port() -> int:
    if _LISTEN_PORT is not None:
        return _LISTEN_PORT
    return int(os.environ.get("PORT", "8005"))
