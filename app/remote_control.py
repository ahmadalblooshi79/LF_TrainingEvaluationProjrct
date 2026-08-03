"""واجهة API وصفحات التحكم المباشر (Live Remote Control Mode) — التطبيق رقم 2.

البث الفوري عبر:
- Server-Sent Events (SSE) لشاشة العرض
- WebSocket على منفذ ثانوي (PORT+1) عند توفره
"""

from __future__ import annotations

import json
import secrets
import time
from datetime import datetime

from flask import (
    Blueprint,
    Response,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    stream_with_context,
    url_for,
)

from app.auth import get_current_user_optional
from app.models.remote_control import RemoteControlAuditLog, RemoteControlSession
from app.permissions import can_use_remote_control, is_system_admin
from app.remote_control_hub import hub

bp = Blueprint("remote_control", __name__)


def _user_can_control(user) -> bool:
    if user is None:
        return False
    return can_use_remote_control(user)


def _audit(
    *,
    session_id: int | None,
    user,
    device_id: str,
    display_id: str,
    action: str,
    detail: dict | None = None,
) -> None:
    db = g.db
    row = RemoteControlAuditLog(
        session_id=session_id,
        user_id=getattr(user, "id", None) if user else None,
        username=getattr(user, "username", "") if user else "",
        device_id=device_id or "",
        display_id=display_id or "",
        action=action,
        detail_json=json.dumps(detail or {}, ensure_ascii=False),
    )
    db.add(row)
    db.commit()


def _active_session_for_display(display_id: str) -> RemoteControlSession | None:
    return (
        g.db.query(RemoteControlSession)
        .filter(
            RemoteControlSession.is_active.is_(True),
            RemoteControlSession.display_id == (display_id or "default"),
        )
        .order_by(RemoteControlSession.id.desc())
        .first()
    )


def _end_session(row: RemoteControlSession, ended_by: str) -> None:
    row.is_active = False
    row.ended_at = datetime.utcnow()
    row.ended_by = ended_by
    g.db.commit()
    hub.publish(
        row.display_id,
        {
            "type": "session_ended",
            "session_token": row.session_token,
            "ended_by": ended_by,
        },
    )


@bp.route("/api/remote-control/status", methods=["GET"])
def api_status():
    user = get_current_user_optional()
    display_id = (request.args.get("display_id") or "default").strip() or "default"
    active = _active_session_for_display(display_id)
    mine = False
    if active and user and active.user_id == user.id:
        mine = True
    return jsonify(
        {
            "ok": True,
            "can_control": _user_can_control(user),
            "logged_in": user is not None,
            "display_id": display_id,
            "active": None
            if active is None
            else {
                "session_token": active.session_token,
                "username": active.username,
                "device_id": active.device_id,
                "device_label": active.device_label,
                "is_locked": bool(active.is_locked),
                "started_at": active.started_at.isoformat() if active.started_at else None,
                "last_path": active.last_path,
                "mine": mine,
            },
            "last_state": hub.last_state(display_id),
        }
    )


@bp.route("/api/remote-control/session/start", methods=["POST"])
def api_session_start():
    user = get_current_user_optional()
    if user is None:
        return jsonify({"ok": False, "error": "login_required"}), 401
    if not _user_can_control(user):
        return jsonify({"ok": False, "error": "forbidden"}), 403

    data = request.get_json(silent=True) or {}
    display_id = (data.get("display_id") or "default").strip() or "default"
    device_id = (data.get("device_id") or "").strip() or secrets.token_hex(8)
    device_label = (data.get("device_label") or "System Tablet").strip()[:200]

    existing = _active_session_for_display(display_id)
    if existing is not None:
        if existing.is_locked and existing.user_id != user.id:
            return (
                jsonify(
                    {
                        "ok": False,
                        "error": "display_locked",
                        "message": "شاشة العرض مقفلة لجلسة أخرى.",
                        "active_user": existing.username,
                    }
                ),
                409,
            )
        if existing.user_id != user.id:
            return (
                jsonify(
                    {
                        "ok": False,
                        "error": "display_busy",
                        "message": "شاشة العرض مُتحكم بها من جهاز آخر.",
                        "active_user": existing.username,
                        "active_device": existing.device_label,
                    }
                ),
                409,
            )
        # نفس المستخدم يستأنف
        existing.device_id = device_id
        existing.device_label = device_label
        g.db.commit()
        token = existing.session_token
        session["rc_session_token"] = token
        session["rc_display_id"] = display_id
        _audit(
            session_id=existing.id,
            user=user,
            device_id=device_id,
            display_id=display_id,
            action="session_resume",
            detail={"device_label": device_label},
        )
        hub.publish(
            display_id,
            {
                "type": "session_started",
                "session_token": token,
                "username": user.username,
                "device_label": device_label,
                "path": existing.last_path or "/dashboard",
                "resumed": True,
            },
        )
        hub.publish(
            display_id,
            {
                "type": "navigate",
                "path": existing.last_path or "/dashboard",
                "payload": {},
                "session_token": token,
                "username": user.username,
            },
        )
        return jsonify(
            {
                "ok": True,
                "session_token": token,
                "display_id": display_id,
                "resumed": True,
            }
        )

    token = secrets.token_urlsafe(24)
    row = RemoteControlSession(
        session_token=token,
        user_id=user.id,
        username=user.username or "",
        device_id=device_id,
        device_label=device_label,
        display_id=display_id,
        is_active=True,
        is_locked=False,
        last_path="/dashboard",
    )
    g.db.add(row)
    g.db.commit()
    session["rc_session_token"] = token
    session["rc_display_id"] = display_id
    _audit(
        session_id=row.id,
        user=user,
        device_id=device_id,
        display_id=display_id,
        action="session_start",
        detail={"device_label": device_label},
    )
    hub.publish(
        display_id,
        {
            "type": "session_started",
            "session_token": token,
            "username": user.username,
            "device_label": device_label,
            "path": row.last_path or "/dashboard",
        },
    )
    # إرسال مسار أولي فوراً حتى لا تبقى شاشة العرض بيضاء بانتظار أول تنقل من التابلت
    hub.publish(
        display_id,
        {
            "type": "navigate",
            "path": row.last_path or "/dashboard",
            "payload": {},
            "session_token": token,
            "username": user.username,
        },
    )
    return jsonify(
        {
            "ok": True,
            "session_token": token,
            "display_id": display_id,
            "resumed": False,
        }
    )


@bp.route("/api/remote-control/session/stop", methods=["POST"])
def api_session_stop():
    user = get_current_user_optional()
    if user is None:
        return jsonify({"ok": False, "error": "login_required"}), 401
    data = request.get_json(silent=True) or {}
    token = (data.get("session_token") or session.get("rc_session_token") or "").strip()
    row = None
    if token:
        row = (
            g.db.query(RemoteControlSession)
            .filter(RemoteControlSession.session_token == token)
            .first()
        )
    if row is None or not row.is_active:
        return jsonify({"ok": True, "stopped": False})
    if row.user_id != user.id and not is_system_admin(user):
        return jsonify({"ok": False, "error": "forbidden"}), 403
    _end_session(row, "user" if row.user_id == user.id else "admin")
    _audit(
        session_id=row.id,
        user=user,
        device_id=row.device_id,
        display_id=row.display_id,
        action="session_stop",
        detail={},
    )
    session.pop("rc_session_token", None)
    return jsonify({"ok": True, "stopped": True})


@bp.route("/api/remote-control/session/lock", methods=["POST"])
def api_session_lock():
    user = get_current_user_optional()
    if user is None:
        return jsonify({"ok": False, "error": "login_required"}), 401
    data = request.get_json(silent=True) or {}
    token = (data.get("session_token") or session.get("rc_session_token") or "").strip()
    lock = bool(data.get("locked", True))
    row = (
        g.db.query(RemoteControlSession)
        .filter(RemoteControlSession.session_token == token, RemoteControlSession.is_active.is_(True))
        .first()
    )
    if row is None:
        return jsonify({"ok": False, "error": "no_session"}), 404
    if row.user_id != user.id and not is_system_admin(user):
        return jsonify({"ok": False, "error": "forbidden"}), 403
    row.is_locked = lock
    g.db.commit()
    _audit(
        session_id=row.id,
        user=user,
        device_id=row.device_id,
        display_id=row.display_id,
        action="session_lock" if lock else "session_unlock",
        detail={},
    )
    hub.publish(
        row.display_id,
        {"type": "session_lock", "locked": lock, "session_token": row.session_token},
    )
    return jsonify({"ok": True, "locked": lock})


@bp.route("/api/remote-control/command", methods=["POST"])
def api_command():
    """أمر من جهاز التحكم (التابلت) إلى شاشة العرض."""
    user = get_current_user_optional()
    if user is None:
        return jsonify({"ok": False, "error": "login_required"}), 401
    if not _user_can_control(user):
        return jsonify({"ok": False, "error": "forbidden"}), 403

    data = request.get_json(silent=True) or {}
    token = (data.get("session_token") or session.get("rc_session_token") or "").strip()
    row = (
        g.db.query(RemoteControlSession)
        .filter(RemoteControlSession.session_token == token, RemoteControlSession.is_active.is_(True))
        .first()
    )
    if row is None:
        return jsonify({"ok": False, "error": "no_session"}), 404
    if row.user_id != user.id:
        return jsonify({"ok": False, "error": "not_controller"}), 403

    cmd_type = (data.get("type") or "navigate").strip()
    path = (data.get("path") or data.get("url") or "").strip()
    payload = data.get("payload") if isinstance(data.get("payload"), dict) else {}
    # لا نبثّ تكبيراً إلى شاشة العرض — كان يسبب scale عشوائياً ثم عودة للوضع الطبيعي
    if cmd_type in ("zoom", "pan"):
        cmd_type = "scroll"
        payload = {
            "scrollX": payload.get("x", payload.get("scrollX", 0)),
            "scrollY": payload.get("y", payload.get("scrollY", 0)),
        }
    elif cmd_type == "scroll":
        payload = {
            "scrollX": payload.get("scrollX", payload.get("x", 0)),
            "scrollY": payload.get("scrollY", payload.get("y", 0)),
        }
    if path:
        row.last_path = path[:500]
    state = {
        "type": cmd_type,
        "path": path or row.last_path,
        "payload": payload,
        "session_token": token,
        "username": user.username,
    }
    row.last_state_json = json.dumps(state, ensure_ascii=False)
    g.db.commit()
    delivered = hub.publish(row.display_id, state)
    _audit(
        session_id=row.id,
        user=user,
        device_id=row.device_id,
        display_id=row.display_id,
        action=f"cmd:{cmd_type}",
        detail={"path": path, "payload": payload},
    )
    return jsonify({"ok": True, "delivered": delivered})


@bp.route("/api/remote-control/stream")
def api_stream():
    """SSE لشاشة العرض — تحديث فوري دون polling."""
    display_id = (request.args.get("display_id") or "default").strip() or "default"
    sub = hub.subscribe(display_id, kind="sse")

    @stream_with_context
    def generate():
        try:
            yield f"event: hello\ndata: {json.dumps({'display_id': display_id}, ensure_ascii=False)}\n\n"
            last_ping = time.time()
            while True:
                try:
                    evt = sub.q.get(timeout=15)
                    yield f"event: remote\ndata: {json.dumps(evt, ensure_ascii=False)}\n\n"
                except Exception:
                    now = time.time()
                    if now - last_ping >= 15:
                        yield f"event: ping\ndata: {json.dumps({'t': now})}\n\n"
                        last_ping = now
        finally:
            hub.unsubscribe(sub)

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@bp.route("/presentation/live")
def presentation_live():
    """شاشة العرض (الكمبيوتر / البروجيكتور) — تتبع جهاز التحكم."""
    display_id = (request.args.get("display_id") or "default").strip() or "default"
    return render_template(
        "presentation_live.html",
        display_id=display_id,
        ws_port_hint=int(request.environ.get("SERVER_PORT") or 8005) + 1,
    )


@bp.route("/admin/remote-control", methods=["GET", "POST"])
def admin_remote_control():
    user = get_current_user_optional()
    if user is None:
        return redirect(url_for("views.login", next="/admin/remote-control"))
    if not is_system_admin(user):
        return redirect(url_for("views.dashboard"))

    if request.method == "POST":
        action = (request.form.get("action") or "").strip()
        sid = request.form.get("session_id", type=int)
        if action == "stop" and sid:
            row = g.db.get(RemoteControlSession, sid)
            if row and row.is_active:
                _end_session(row, "admin")
                _audit(
                    session_id=row.id,
                    user=user,
                    device_id=row.device_id,
                    display_id=row.display_id,
                    action="admin_stop",
                    detail={},
                )
        return redirect(url_for("remote_control.admin_remote_control"))

    active = (
        g.db.query(RemoteControlSession)
        .filter(RemoteControlSession.is_active.is_(True))
        .order_by(RemoteControlSession.id.desc())
        .all()
    )
    logs = (
        g.db.query(RemoteControlAuditLog)
        .order_by(RemoteControlAuditLog.id.desc())
        .limit(100)
        .all()
    )
    return render_template(
        "admin_remote_control.html",
        user=user,
        active_sessions=active,
        audit_logs=logs,
    )
