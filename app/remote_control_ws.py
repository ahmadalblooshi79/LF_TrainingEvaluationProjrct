"""خادم WebSocket ثانوي للتحكم المباشر (يعمل بجانب Waitress)."""

from __future__ import annotations

import json
import logging
import threading
from typing import Any

from app.remote_control_hub import hub

_log = logging.getLogger("remote_control_ws")
_started = False
_lock = threading.Lock()


def start_remote_control_ws_server(host: str = "0.0.0.0", port: int = 8006) -> bool:
    """تشغيل خادم WS في خيط خلفي. يعيد False إن تعذّر الاستيراد أو المنفذ مشغول."""
    global _started
    with _lock:
        if _started:
            return True
        try:
            from websockets.sync.server import serve
        except ImportError:
            _log.warning("websockets package not installed — streaming via SSE only.")
            return False

        def handler(websocket: Any) -> None:
            display_id = "default"
            try:
                path = getattr(websocket, "request", None)
                raw_path = ""
                if path is not None:
                    raw_path = getattr(path, "path", "") or ""
                if "display_id=" in raw_path:
                    display_id = raw_path.split("display_id=", 1)[1].split("&", 1)[0] or "default"
                hub.register_ws(websocket, display_id)
                websocket.send(
                    json.dumps(
                        {"type": "hello", "display_id": display_id, "channel": "ws"},
                        ensure_ascii=False,
                    )
                )
                last = hub.last_state(display_id)
                if last:
                    websocket.send(json.dumps(last, ensure_ascii=False))
                for _msg in websocket:
                    # العرض يستقبل فقط؛ أوامر التحكم عبر REST من التابلت
                    pass
            except Exception as exc:
                _log.debug("ws client closed: %s", exc)
            finally:
                hub.unregister_ws(websocket)

        def run() -> None:
            try:
                with serve(handler, host, port) as server:
                    _log.info("Remote Control WebSocket on %s:%s", host, port)
                    server.serve_forever()
            except OSError as exc:
                _log.warning("Could not start WebSocket on %s:%s — %s", host, port, exc)

        t = threading.Thread(target=run, name="rc-websocket", daemon=True)
        t.start()
        _started = True
        return True
