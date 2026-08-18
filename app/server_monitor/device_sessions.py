"""تسجيل الأجهزة المتصلة ونبضات النشاط."""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from app.models.server_monitor import ConnectedDevice, ServerActivityLog, SyncOperationLog


def _military_number_for_user(user) -> str:
    return (getattr(user, "username", "") or "").strip()


def register_or_update_device(
    db: Session,
    *,
    device_id: str,
    device_name: str = "",
    device_ip: str = "",
    user=None,
    user_agent: str = "",
    sync_status: str = "idle",
    pending_sync_count: int = 0,
    is_login: bool = False,
) -> ConnectedDevice:
    did = (device_id or "").strip()
    if not did:
        raise ValueError("device_id required")
    row = db.query(ConnectedDevice).filter(ConnectedDevice.device_id == did).one_or_none()
    now = datetime.utcnow()
    if row is None:
        row = ConnectedDevice(device_id=did)
        db.add(row)
        row.login_at = now if is_login else None
    elif is_login:
        row.login_at = now

    row.device_name = (device_name or row.device_name or "جهاز").strip()
    row.device_ip = (device_ip or row.device_ip or "").strip()
    row.user_agent = (user_agent or row.user_agent or "")[:512]
    row.sync_status = (sync_status or "idle").strip()[:32]
    row.pending_sync_count = max(0, int(pending_sync_count or 0))
    row.last_activity_at = now
    row.status = "online"
    if user is not None:
        row.user_id = int(user.id)
        row.military_number = _military_number_for_user(user)
        row.judge_name = (getattr(user, "full_name", "") or "").strip()
    row.updated_at = now
    return row


def mark_device_offline_stale(db: Session, *, minutes: int = 3) -> int:
    cutoff = datetime.utcnow() - timedelta(minutes=minutes)
    rows = (
        db.query(ConnectedDevice)
        .filter(ConnectedDevice.status == "online")
        .filter(ConnectedDevice.last_activity_at < cutoff)
        .all()
    )
    for r in rows:
        r.status = "offline"
    return len(rows)


def devices_summary(db: Session) -> dict:
    mark_device_offline_stale(db)
    total = db.query(func.count(ConnectedDevice.id)).scalar() or 0
    online = (
        db.query(func.count(ConnectedDevice.id))
        .filter(ConnectedDevice.status == "online")
        .scalar()
        or 0
    )
    syncing = (
        db.query(func.count(ConnectedDevice.id))
        .filter(ConnectedDevice.sync_status == "syncing")
        .scalar()
        or 0
    )
    return {"total_devices": total, "online_devices": online, "syncing_devices": syncing}


def list_devices(db: Session, *, limit: int = 200) -> list[ConnectedDevice]:
    mark_device_offline_stale(db)
    return (
        db.query(ConnectedDevice)
        .order_by(desc(ConnectedDevice.last_activity_at))
        .limit(limit)
        .all()
    )


def log_activity(
    db: Session,
    *,
    category: str,
    message: str,
    level: str = "info",
    user_id: int | None = None,
    device_id: str = "",
    details: dict | None = None,
) -> None:
    db.add(
        ServerActivityLog(
            category=(category or "general")[:64],
            level=(level or "info")[:16],
            message=message or "",
            user_id=user_id,
            device_id=(device_id or "")[:128],
            details_json=json.dumps(details or {}, ensure_ascii=False)[:8000],
        )
    )


def log_sync_operation(
    db: Session,
    *,
    client_operation_id: str,
    device_id: str,
    user_id: int | None,
    operation_type: str,
    target_url: str,
    status: str,
    error_message: str = "",
    payload_hash: str = "",
) -> SyncOperationLog:
    op_id = (client_operation_id or "").strip()
    existing = (
        db.query(SyncOperationLog)
        .filter(SyncOperationLog.client_operation_id == op_id)
        .one_or_none()
    )
    if existing is not None:
        return existing
    row = SyncOperationLog(
        client_operation_id=op_id,
        device_id=(device_id or "")[:128],
        user_id=user_id,
        operation_type=(operation_type or "")[:64],
        target_url=(target_url or "")[:700],
        status=(status or "pending")[:32],
        error_message=(error_message or "")[:4000],
        payload_hash=(payload_hash or "")[:64],
        synced_at=datetime.utcnow() if status == "synced" else None,
    )
    db.add(row)
    return row


def recent_activity_logs(db: Session, *, limit: int = 100, category: str = "") -> list[ServerActivityLog]:
    q = db.query(ServerActivityLog).order_by(desc(ServerActivityLog.created_at))
    if category:
        q = q.filter(ServerActivityLog.category == category)
    return q.limit(limit).all()


def recent_sync_logs(db: Session, *, limit: int = 100) -> list[SyncOperationLog]:
    return (
        db.query(SyncOperationLog)
        .order_by(desc(SyncOperationLog.created_at))
        .limit(limit)
        .all()
    )
