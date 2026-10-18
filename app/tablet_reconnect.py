# -*- coding: utf-8 -*-
"""HMAC reconnect tickets for tablet judges — no DB table, no password storage."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

from app.config import SECRET_KEY

TICKET_TTL_SECONDS = 180 * 24 * 3600
_PREFIX = "tablet-reconnect|"


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64url_decode(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


def issue_reconnect_ticket(user_id: int, device_id: str = "") -> str:
    payload = json.dumps(
        {
            "u": int(user_id),
            "d": (device_id or "").strip(),
            "e": int(time.time()) + TICKET_TTL_SECONDS,
            "v": 1,
        },
        separators=(",", ":"),
        ensure_ascii=False,
    )
    body = _b64url(payload.encode("utf-8"))
    sig = hmac.new(
        (SECRET_KEY or "").encode("utf-8"),
        f"{_PREFIX}{body}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"{body}.{sig}"


def verify_reconnect_ticket(
    token: str,
    expected_user_id: int,
    device_id: str = "",
) -> bool:
    raw = (token or "").strip()
    if "." not in raw:
        return False
    body, sig = raw.rsplit(".", 1)
    if not body or not sig:
        return False
    expected = hmac.new(
        (SECRET_KEY or "").encode("utf-8"),
        f"{_PREFIX}{body}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, sig):
        return False
    try:
        data = json.loads(_b64url_decode(body).decode("utf-8"))
    except Exception:
        return False
    if int(data.get("v") or 0) != 1:
        return False
    try:
        uid = int(data.get("u"))
        exp = int(data.get("e") or 0)
    except (TypeError, ValueError):
        return False
    if uid != int(expected_user_id):
        return False
    if exp < int(time.time()):
        return False
    bound = (data.get("d") or "").strip()
    got = (device_id or "").strip()
    if bound and got and bound != got:
        return False
    return True
