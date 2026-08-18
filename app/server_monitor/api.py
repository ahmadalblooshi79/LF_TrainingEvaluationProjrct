"""واجهات API لمراقبة الخادم والمزامنة والأجهزة."""

from __future__ import annotations

import json
from datetime import datetime

from flask import Blueprint, abort, g, jsonify, request, url_for

from app.auth import get_current_user_optional
from app.permissions import is_system_admin
from app.server_monitor.device_sessions import (
    devices_summary,
    list_devices,
    log_activity,
    recent_activity_logs,
    recent_sync_logs,
    register_or_update_device,
)
from app.server_monitor.metrics import server_status_payload
from app.server_monitor.sync_processor import process_sync_batch

server_api_bp = Blueprint("server_api", __name__)


def _require_user():
    user = get_current_user_optional()
    if not user:
        abort(401)
    return user


def _require_admin():
    user = _require_user()
    if not is_system_admin(user):
        abort(403)
    return user


@server_api_bp.post("/api/device/register")
def api_device_register():
    user = _require_user()
    data = request.get_json(silent=True) or {}
    device_id = (data.get("device_id") or request.headers.get("X-LF-Device-Id") or "").strip()
    if not device_id:
        return jsonify({"ok": False, "error": "device_id_required"}), 400
    db = g.db
    row = register_or_update_device(
        db,
        device_id=device_id,
        device_name=(data.get("device_name") or "").strip(),
        device_ip=(request.remote_addr or "").strip(),
        user=user,
        user_agent=(request.headers.get("User-Agent") or "")[:512],
        is_login=bool(data.get("is_login")),
    )
    log_activity(
        db,
        category="login",
        message=f"تسجيل جهاز: {row.device_name}",
        user_id=user.id,
        device_id=device_id,
        details={"ip": row.device_ip, "military_number": row.military_number},
    )
    db.commit()
    return jsonify(
        {
            "ok": True,
            "device_id": row.device_id,
            "military_number": row.military_number,
            "judge_name": row.judge_name,
        }
    )


@server_api_bp.post("/api/device/heartbeat")
def api_device_heartbeat():
    user = _require_user()
    data = request.get_json(silent=True) or {}
    device_id = (data.get("device_id") or request.headers.get("X-LF-Device-Id") or "").strip()
    if not device_id:
        return jsonify({"ok": False}), 400
    db = g.db
    register_or_update_device(
        db,
        device_id=device_id,
        device_name=(data.get("device_name") or "").strip(),
        device_ip=(request.remote_addr or "").strip(),
        user=user,
        sync_status=(data.get("sync_status") or "idle").strip(),
        pending_sync_count=int(data.get("pending_sync_count") or 0),
    )
    db.commit()
    return jsonify({"ok": True, "server_time": datetime.utcnow().isoformat() + "Z"})


@server_api_bp.post("/api/sync/batch")
def api_sync_batch():
    user = _require_user()
    data = request.get_json(silent=True) or {}
    ops = data.get("operations") or []
    if not isinstance(ops, list):
        return jsonify({"ok": False, "error": "invalid_operations"}), 400
    result = process_sync_batch(db=g.db, user=user, request=request, operations=ops)
    return jsonify(result)


@server_api_bp.get("/api/server/status")
def api_server_status():
    _require_admin()
    return jsonify({"ok": True, **server_status_payload()})


@server_api_bp.get("/api/server/devices")
def api_server_devices():
    _require_admin()
    rows = list_devices(g.db)
    out = []
    for r in rows:
        out.append(
            {
                "device_name": r.device_name,
                "device_ip": r.device_ip,
                "military_number": r.military_number,
                "judge_name": r.judge_name,
                "username": r.military_number,
                "login_time": r.login_at.isoformat() + "Z" if r.login_at else "",
                "last_activity": r.last_activity_at.isoformat() + "Z" if r.last_activity_at else "",
                "status": r.status,
                "sync_status": r.sync_status,
                "pending_sync_count": r.pending_sync_count,
            }
        )
    summary = devices_summary(g.db)
    return jsonify({"ok": True, "summary": summary, "devices": out})


@server_api_bp.get("/api/server/logs")
def api_server_logs():
    _require_admin()
    category = (request.args.get("category") or "").strip()
    kind = (request.args.get("kind") or "activity").strip()
    limit = min(500, max(1, int(request.args.get("limit") or 100)))
    db = g.db
    if kind == "sync":
        rows = recent_sync_logs(db, limit=limit)
        items = [
            {
                "id": r.id,
                "client_operation_id": r.client_operation_id,
                "device_id": r.device_id,
                "operation_type": r.operation_type,
                "target_url": r.target_url,
                "status": r.status,
                "error_message": r.error_message,
                "created_at": r.created_at.isoformat() + "Z" if r.created_at else "",
                "synced_at": r.synced_at.isoformat() + "Z" if r.synced_at else "",
            }
            for r in rows
        ]
    else:
        rows = recent_activity_logs(db, limit=limit, category=category)
        items = [
            {
                "id": r.id,
                "category": r.category,
                "level": r.level,
                "message": r.message,
                "device_id": r.device_id,
                "created_at": r.created_at.isoformat() + "Z" if r.created_at else "",
                "details": r.details_json,
            }
            for r in rows
        ]
    return jsonify({"ok": True, "items": items})


@server_api_bp.get("/api/server/qr")
def api_server_qr():
    _require_admin()
    status = server_status_payload()
    url = status.get("access_url") or "/"
    # QR بسيط كنص SVG — بدون مكتبات خارجية (نمط placeholder مع الرابط)
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200" viewBox="0 0 200 200">'
        f'<rect width="200" height="200" fill="#fff"/>'
        f'<text x="100" y="95" text-anchor="middle" font-size="11" fill="#4a4037">امسح من التابلت</text>'
        f'<text x="100" y="115" text-anchor="middle" font-size="9" fill="#6b5a48">{url}</text>'
        f"</svg>"
    )
    from flask import Response

    return Response(svg, mimetype="image/svg+xml")
