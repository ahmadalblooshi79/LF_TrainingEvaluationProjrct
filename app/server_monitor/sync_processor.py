"""معالجة طابور المزامنة من التابلت."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from flask import Request
from sqlalchemy.orm import Session

from app.server_monitor.device_sessions import log_activity, log_sync_operation, register_or_update_device


def _payload_hash(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8", errors="replace")
    return hashlib.sha256(data).hexdigest()[:64]


def process_sync_batch(
    db: Session,
    *,
    user,
    request: Request,
    operations: list[dict[str, Any]],
) -> dict:
    device_id = (request.headers.get("X-LF-Device-Id") or (request.get_json(silent=True) or {}).get("device_id") or "").strip()
    device_name = (request.headers.get("X-LF-Device-Name") or (request.get_json(silent=True) or {}).get("device_name") or "").strip()
    device_ip = (request.remote_addr or "").strip()

    if device_id:
        register_or_update_device(
            db,
            device_id=device_id,
            device_name=device_name,
            device_ip=device_ip,
            user=user,
            user_agent=(request.headers.get("User-Agent") or "")[:512],
            sync_status="syncing",
            pending_sync_count=len(operations),
        )

    results: list[dict] = []
    synced = 0
    skipped = 0
    failed = 0

    for op in operations:
        op_id = (op.get("client_operation_id") or "").strip()
        op_type = (op.get("type") or "http_post").strip()
        url = (op.get("url") or "").strip()
        if not op_id or not url:
            failed += 1
            results.append({"client_operation_id": op_id, "ok": False, "error": "invalid_op"})
            continue

        existing = log_sync_operation(
            db,
            client_operation_id=op_id,
            device_id=device_id,
            user_id=getattr(user, "id", None),
            operation_type=op_type,
            target_url=url,
            status="pending",
        )
        if existing.synced_at is not None and existing.status == "synced":
            skipped += 1
            results.append({"client_operation_id": op_id, "ok": True, "duplicate": True})
            continue

        try:
            ok = _replay_operation(db, user=user, op=op, request=request)
            if ok:
                existing.status = "synced"
                existing.synced_at = __import__("datetime").datetime.utcnow()
                synced += 1
                results.append({"client_operation_id": op_id, "ok": True})
            else:
                existing.status = "failed"
                existing.error_message = "replay_failed"
                failed += 1
                results.append({"client_operation_id": op_id, "ok": False, "error": "replay_failed"})
        except Exception as exc:
            existing.status = "failed"
            existing.error_message = str(exc)[:4000]
            failed += 1
            results.append({"client_operation_id": op_id, "ok": False, "error": str(exc)[:200]})

    if device_id:
        register_or_update_device(
            db,
            device_id=device_id,
            device_name=device_name,
            device_ip=device_ip,
            user=user,
            sync_status="idle" if failed == 0 else "error",
            pending_sync_count=failed,
        )

    log_activity(
        db,
        category="sync",
        message=f"مزامنة دفعة: نجح={synced} تخطي={skipped} فشل={failed}",
        user_id=getattr(user, "id", None),
        device_id=device_id,
        details={"synced": synced, "skipped": skipped, "failed": failed},
    )
    db.commit()
    return {"ok": True, "synced": synced, "skipped": skipped, "failed": failed, "results": results}


def _replay_operation(db: Session, *, user, op: dict, request: Request) -> bool:
    op_type = (op.get("type") or "").strip()
    url = (op.get("url") or "").strip()
    if op_type == "eval_save" or url.endswith("/save-results"):
        return _replay_eval_save(db, user=user, op=op)
    if op_type == "media_upload" or "/eval-criterion-media/upload" in url:
        return _replay_media_upload(db, user=user, op=op, request=request)
    return False


def _replay_eval_save(db: Session, *, user, op: dict) -> bool:
    from app.views import _evaluation_commit_payload_save, _current_workspace_exercise
    from app.models import EvaluationListPdfItem

    payload_json = (op.get("payload_json") or "").strip()
    item_id = int(op.get("evaluation_list_item_id") or op.get("item_id") or 0)
    if not payload_json or not item_id:
        return False
    item = db.get(EvaluationListPdfItem, item_id)
    ex = _current_workspace_exercise(db, user)
    if not item or not ex or item.exercise_id != ex.id:
        return False
    _evaluation_commit_payload_save(db, user=user, item=item, current_exercise=ex, raw=payload_json)
    return True


def _replay_media_upload(db: Session, *, user, op: dict, request: Request) -> bool:
    import base64
    from app.eval_criterion_media import persist_criterion_medium

    b64 = (op.get("file_base64") or "").strip()
    if not b64:
        return False
    raw = base64.b64decode(b64)
    row_index = int(op.get("row_index") or 0)
    media_kind = (op.get("media_kind") or "photo").strip()
    li_pk = op.get("evaluation_list_item_id")
    ba_pk = op.get("bundle_action_eval_id")
    ex_id = int(op.get("exercise_id") or 0)
    unit_key = (op.get("unit_level_key") or "").strip()
    mime = (op.get("mime_type") or "image/jpeg").strip()
    persist_criterion_medium(
        db,
        exercise_id=ex_id,
        unit_level_key=unit_key,
        list_item_id=int(li_pk) if li_pk else None,
        bundle_action_eval_id=int(ba_pk) if ba_pk else None,
        row_index=row_index,
        media_kind=media_kind,
        mime_type_in=mime,
        bin_data=raw,
        uploaded_by_id=int(user.id),
    )
    return True
