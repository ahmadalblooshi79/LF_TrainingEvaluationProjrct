"""عميل HTTP للواجهة المحلية على تابلت المحكم داخل الشبكة التشغيلية فقط."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

DEFAULT_PORT = 8765
CONNECT_TIMEOUT = 4
READ_TIMEOUT = 25


def _url(ip: str, port: int, path: str) -> str:
    host = (ip or "").strip()
    if not host:
        raise ValueError("device_ip required")
    p = int(port or DEFAULT_PORT)
    if not path.startswith("/"):
        path = "/" + path
    return f"http://{host}:{p}{path}"


def tablet_request(
    ip: str,
    token: str,
    path: str,
    *,
    port: int = DEFAULT_PORT,
    method: str = "GET",
    body: dict[str, Any] | None = None,
    timeout: float | None = None,
) -> tuple[int, dict[str, Any] | bytes]:
    headers = {
        "Accept": "application/json",
        "X-LF-Tablet-Token": (token or "").strip(),
        "Authorization": f"Bearer {(token or '').strip()}",
    }
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(
        _url(ip, port, path),
        data=data,
        headers=headers,
        method=method.upper(),
    )
    t = timeout if timeout is not None else (READ_TIMEOUT if method.upper() != "GET" else CONNECT_TIMEOUT)
    try:
        with urllib.request.urlopen(req, timeout=t) as resp:
            raw = resp.read()
            ctype = (resp.headers.get("Content-Type") or "").lower()
            if "application/json" in ctype or raw[:1] in (b"{", b"["):
                try:
                    return int(resp.status), json.loads(raw.decode("utf-8"))
                except Exception:
                    return int(resp.status), {"ok": False, "raw": raw[:400].decode("utf-8", "replace")}
            return int(resp.status), raw
    except urllib.error.HTTPError as exc:
        raw = exc.read() if exc.fp else b""
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except Exception:
            parsed = {"ok": False, "error": str(exc), "body": raw[:400].decode("utf-8", "replace")}
        return int(exc.code), parsed
    except Exception as exc:
        return 0, {"ok": False, "error": str(exc)}


def probe_health(ip: str, token: str, port: int = DEFAULT_PORT) -> dict[str, Any]:
    status, payload = tablet_request(ip, token, "/v1/health", port=port, timeout=CONNECT_TIMEOUT)
    if status == 200 and isinstance(payload, dict) and payload.get("ok"):
        return {"ready": True, "status": "READY", **payload}
    if status == 0:
        return {"ready": False, "status": "UNREACHABLE", "error": payload.get("error") if isinstance(payload, dict) else ""}
    return {"ready": False, "status": "NOT_READY", "http": status, "payload": payload}


def get_identity(ip: str, token: str, port: int = DEFAULT_PORT) -> dict[str, Any]:
    status, payload = tablet_request(ip, token, "/v1/identity", port=port)
    if status == 200 and isinstance(payload, dict):
        return payload
    return {"ok": False, "http": status, "error": payload}


def get_summary(ip: str, token: str, port: int = DEFAULT_PORT) -> dict[str, Any]:
    status, payload = tablet_request(ip, token, "/v1/summary", port=port, timeout=10)
    if status == 200 and isinstance(payload, dict):
        return payload
    return {"ok": False, "http": status, "error": payload}


def get_evaluations(ip: str, token: str, port: int = DEFAULT_PORT) -> dict[str, Any]:
    status, payload = tablet_request(ip, token, "/v1/evaluations", port=port, timeout=15)
    if status == 200 and isinstance(payload, dict):
        return payload
    return {"ok": False, "http": status, "error": payload}


def pull_evaluation_package(
    ip: str,
    token: str,
    eval_item_id: int,
    *,
    port: int = DEFAULT_PORT,
) -> tuple[int, bytes | dict[str, Any]]:
    return tablet_request(
        ip,
        token,
        f"/v1/evaluations/{int(eval_item_id)}/package",
        port=port,
        timeout=120,
    )


def ack_received(
    ip: str,
    token: str,
    *,
    eval_item_ids: list[int],
    port: int = DEFAULT_PORT,
) -> dict[str, Any]:
    status, payload = tablet_request(
        ip,
        token,
        "/v1/ack",
        port=port,
        method="POST",
        body={"eval_item_ids": [int(x) for x in eval_item_ids], "keep_local": True},
        timeout=15,
    )
    if isinstance(payload, dict):
        payload["http"] = status
        return payload
    return {"ok": False, "http": status}


def push_update(
    ip: str,
    token: str,
    *,
    eval_item_ids: list[int] | None = None,
    scope: str = "all",
    port: int = DEFAULT_PORT,
) -> dict[str, Any]:
    status, payload = tablet_request(
        ip,
        token,
        "/v1/update",
        port=port,
        method="POST",
        body={"scope": scope, "eval_item_ids": eval_item_ids or []},
        timeout=120,
    )
    if isinstance(payload, dict):
        payload["http"] = status
        return payload
    return {"ok": False, "http": status}
