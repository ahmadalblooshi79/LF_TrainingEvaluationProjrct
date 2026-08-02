"""محور بث أوامر التحكم المباشر (SSE + WebSocket)."""

from __future__ import annotations

import json
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class _Subscriber:
    q: queue.Queue = field(default_factory=lambda: queue.Queue(maxsize=200))
    display_id: str = "default"
    kind: str = "sse"  # sse | ws


class RemoteControlHub:
    """بث فوري لحالة العرض — بدون polling من جهة العرض."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._subs: list[_Subscriber] = []
        self._last_by_display: dict[str, dict[str, Any]] = {}
        self._ws_clients: list[Any] = []

    def subscribe(self, display_id: str = "default", kind: str = "sse") -> _Subscriber:
        sub = _Subscriber(display_id=display_id or "default", kind=kind)
        with self._lock:
            self._subs.append(sub)
            last = self._last_by_display.get(sub.display_id)
            if last:
                try:
                    sub.q.put_nowait(last)
                except queue.Full:
                    pass
        return sub

    def unsubscribe(self, sub: _Subscriber) -> None:
        with self._lock:
            if sub in self._subs:
                self._subs.remove(sub)

    def publish(self, display_id: str, event: dict[str, Any]) -> int:
        display_id = display_id or "default"
        payload = dict(event)
        payload.setdefault("display_id", display_id)
        payload.setdefault("ts", time.time())
        with self._lock:
            self._last_by_display[display_id] = payload
            dead: list[_Subscriber] = []
            delivered = 0
            for sub in self._subs:
                if sub.display_id not in (display_id, "*"):
                    continue
                try:
                    sub.q.put_nowait(payload)
                    delivered += 1
                except queue.Full:
                    try:
                        sub.q.get_nowait()
                    except queue.Empty:
                        pass
                    try:
                        sub.q.put_nowait(payload)
                        delivered += 1
                    except queue.Full:
                        dead.append(sub)
            for d in dead:
                if d in self._subs:
                    self._subs.remove(d)
            # WebSocket clients (sync)
            alive_ws = []
            for ws in self._ws_clients:
                try:
                    if getattr(ws, "display_id", "default") not in (display_id, "*"):
                        alive_ws.append(ws)
                        continue
                    ws.send(json.dumps(payload, ensure_ascii=False))
                    delivered += 1
                    alive_ws.append(ws)
                except Exception:
                    pass
            self._ws_clients = alive_ws
        return delivered

    def last_state(self, display_id: str = "default") -> dict[str, Any] | None:
        with self._lock:
            return self._last_by_display.get(display_id or "default")

    def register_ws(self, ws: Any, display_id: str = "default") -> None:
        ws.display_id = display_id or "default"
        with self._lock:
            self._ws_clients.append(ws)

    def unregister_ws(self, ws: Any) -> None:
        with self._lock:
            if ws in self._ws_clients:
                self._ws_clients.remove(ws)


hub = RemoteControlHub()
