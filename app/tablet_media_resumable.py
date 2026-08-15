"""رفع وسائط تابلت مجزّأ وقابل للاستئناف (Chunked / Resumable)."""
from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from flask import g, jsonify, request
from sqlalchemy.orm import Session

from app.config import EVAL_CRITERION_MEDIA_DIR
from app.eval_criterion_media import (
    ALLOWED_PHOTO_TYPES,
    ALLOWED_VIDEO_TYPES,
    ext_for_mime,
    mime_base,
    persist_criterion_medium_from_path,
)
from app.models import EvaluationCriterionMedia, User

# 10 MB default chunk — قابل للضبط من العميل ضمن حدود معقولة
DEFAULT_CHUNK_SIZE = 10 * 1024 * 1024
MIN_CHUNK_SIZE = 1 * 1024 * 1024
MAX_CHUNK_SIZE = 32 * 1024 * 1024
# هامش مساحة حرة مطلوب على السيرفر فوق حجم الملف
SERVER_FREE_MARGIN = 50 * 1024 * 1024

ALLOWED_PHOTO_TYPES_EXT = ALLOWED_PHOTO_TYPES | frozenset(
    {"image/heic", "image/heif", "image/jpg"}
)
ALLOWED_VIDEO_TYPES_EXT = ALLOWED_VIDEO_TYPES | frozenset(
    {
        "video/mpeg",
        "video/3gpp",
        "video/3gpp2",
        "video/x-m4v",
        "video/quicktime",
    }
)


def _sessions_root() -> Path:
    root = (EVAL_CRITERION_MEDIA_DIR / "_upload_sessions").resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _session_dir(upload_session_id: str) -> Path | None:
    sid = (upload_session_id or "").strip()
    if not sid or ".." in sid or "/" in sid or "\\" in sid:
        return None
    d = (_sessions_root() / sid).resolve()
    try:
        d.relative_to(_sessions_root())
    except ValueError:
        return None
    return d


def _read_meta(session_dir: Path) -> dict[str, Any]:
    meta_path = session_dir / "meta.json"
    if not meta_path.is_file():
        return {}
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_meta(session_dir: Path, meta: dict[str, Any]) -> None:
    meta["updated_at"] = datetime.utcnow().isoformat() + "Z"
    (session_dir / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=0),
        encoding="utf-8",
    )


def _disk_free(path: Path) -> int:
    try:
        return int(shutil.disk_usage(str(path)).free)
    except Exception:
        return 0


def _sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            block = f.read(chunk_size)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def _final_relpath(
    *,
    exercise_id: int,
    user_id: int,
    media_kind: str,
    mime: str,
    client_uuid: str,
) -> str:
    mk = "video" if media_kind == "video" else "photo"
    folder = "videos" if mk == "video" else "images"
    ext = ext_for_mime(mime, mk)
    safe = (client_uuid or uuid.uuid4().hex).replace("-", "")[:64]
    if not safe:
        safe = uuid.uuid4().hex
    return (
        f"uploads/exercises/{int(exercise_id)}/judges/{int(user_id)}/"
        f"{folder}/{safe}{ext}"
    )


def init_upload(user: User, db: Session) -> tuple[dict, int]:
    data = request.get_json(silent=True) or {}
    client_uuid = (data.get("client_uuid") or data.get("client_op_id") or "").strip()
    if not client_uuid:
        return {"ok": False, "error": "client_uuid_required"}, 400

    # Idempotent: نفس client_uuid لمستخدم → جلسة موجودة أو وسائط مكتملة
    existing_media = (
        db.query(EvaluationCriterionMedia)
        .filter(
            EvaluationCriterionMedia.uploaded_by_id == int(user.id),
            EvaluationCriterionMedia.client_op_id == client_uuid,
        )
        .first()
    )
    if existing_media is not None:
        return {
            "ok": True,
            "already_received": True,
            "server_media_id": int(existing_media.id),
            "upload_session_id": None,
            "status": "SYNCED",
        }, 200

    # جلسة سابقة لنفس client_uuid
    for d in _sessions_root().iterdir():
        if not d.is_dir():
            continue
        meta = _read_meta(d)
        if (
            meta.get("user_id") == int(user.id)
            and meta.get("client_uuid") == client_uuid
            and meta.get("status") not in ("completed", "cancelled")
        ):
            received = sorted(int(x) for x in (meta.get("received_chunks") or []))
            next_chunk = 0
            while next_chunk in received:
                next_chunk += 1
            return {
                "ok": True,
                "resumed": True,
                "upload_session_id": d.name,
                "server_media_id": meta.get("server_media_id"),
                "chunk_size": int(meta.get("chunk_size") or DEFAULT_CHUNK_SIZE),
                "next_chunk": next_chunk,
                "total_chunks": int(meta.get("total_chunks") or 0),
                "received_chunks": received,
                "file_size": int(meta.get("file_size") or 0),
            }, 200

    media_kind = (data.get("media_kind") or "photo").strip().lower()
    if media_kind not in ("photo", "video", "image"):
        return {"ok": False, "error": "kind"}, 400
    if media_kind == "image":
        media_kind = "photo"
    mime = mime_base(data.get("mime_type") or "")
    allowed = ALLOWED_VIDEO_TYPES_EXT if media_kind == "video" else ALLOWED_PHOTO_TYPES_EXT
    if mime and mime not in allowed:
        # تخمين من الامتداد لاحقاً — ارفض فقط إن وُجد MIME صريح غير مسموح
        return {"ok": False, "error": "mime", "code": "INVALID_MIME"}, 415

    try:
        file_size = int(data.get("file_size") or 0)
    except (TypeError, ValueError):
        file_size = 0
    if file_size <= 0:
        return {"ok": False, "error": "file_size"}, 400

    free = _disk_free(EVAL_CRITERION_MEDIA_DIR)
    if free < file_size + SERVER_FREE_MARGIN:
        return {
            "ok": False,
            "error": "INSUFFICIENT_SERVER_STORAGE",
            "code": "INSUFFICIENT_SERVER_STORAGE",
            "free_bytes": free,
            "needed_bytes": file_size + SERVER_FREE_MARGIN,
        }, 507

    try:
        chunk_size = int(data.get("chunk_size") or DEFAULT_CHUNK_SIZE)
    except (TypeError, ValueError):
        chunk_size = DEFAULT_CHUNK_SIZE
    chunk_size = max(MIN_CHUNK_SIZE, min(MAX_CHUNK_SIZE, chunk_size))
    total_chunks = max(1, (file_size + chunk_size - 1) // chunk_size)

    li_raw = data.get("evaluation_list_item_id")
    ba_raw = data.get("bundle_action_eval_id")
    li_id = int(li_raw) if li_raw not in (None, "", 0, "0") else None
    ba_id = int(ba_raw) if ba_raw not in (None, "", 0, "0") else None
    if li_id is not None and li_id <= 0:
        li_id = None
    if ba_id is not None and ba_id <= 0:
        ba_id = None
    if (li_id is None and ba_id is None) or (li_id is not None and ba_id is not None):
        return {"ok": False, "error": "scope"}, 400

    row_index = int(data.get("row_index") or 0)
    checksum = (data.get("checksum") or data.get("file_checksum") or "").strip().lower()

    # صلاحية الرفع عبر نفس منطق النظام
    from app.views import (
        _eval_crit_user_can_upload_media,
        _eval_row_canonical_saved_for_crit_upload,
    )
    from app.models.domain import (
        EvaluationListPdfItem,
        ExercisePlannerFlowBundle,
        ExercisePlannerFlowBundleActionEval,
    )

    exercise_id = 0
    unit_key = ""
    if li_id is not None:
        item = db.get(EvaluationListPdfItem, li_id)
        if item is None:
            return {"ok": False, "error": "item"}, 404
        exercise_id = int(item.exercise_id or 0)
        unit_key = (item.unit_level_key or "").strip()
    else:
        ar = db.get(ExercisePlannerFlowBundleActionEval, int(ba_id))
        if ar is None:
            return {"ok": False, "error": "action"}, 404
        bd = db.get(ExercisePlannerFlowBundle, int(ar.bundle_id))
        if bd is None:
            return {"ok": False, "error": "bundle"}, 404
        exercise_id = int(bd.exercise_id)
        unit_key = (bd.unit_level_key or "").strip()

    canon = _eval_row_canonical_saved_for_crit_upload(
        db,
        exercise_id=int(exercise_id),
        list_item_id=li_id,
        bundle_action_eval_id=ba_id,
    )
    if not _eval_crit_user_can_upload_media(
        db,
        user,
        exercise_id=int(exercise_id),
        unit_level_key=unit_key,
        list_item_id=li_id,
        bundle_action_eval_id=ba_id,
        canonical_saved=canon,
    ):
        return {"ok": False, "error": "forbidden"}, 403

    sid = uuid.uuid4().hex
    sdir = _sessions_root() / sid
    sdir.mkdir(parents=True, exist_ok=True)
    (sdir / "chunks").mkdir(exist_ok=True)

    meta = {
        "upload_session_id": sid,
        "client_uuid": client_uuid,
        "user_id": int(user.id),
        "exercise_id": int(exercise_id),
        "unit_level_key": unit_key,
        "evaluation_list_item_id": li_id,
        "bundle_action_eval_id": ba_id,
        "row_index": row_index,
        "media_kind": media_kind,
        "mime_type": mime or ("video/mp4" if media_kind == "video" else "image/jpeg"),
        "file_size": file_size,
        "checksum": checksum,
        "original_filename": (data.get("original_filename") or "")[:240],
        "chunk_size": chunk_size,
        "total_chunks": total_chunks,
        "received_chunks": [],
        "status": "ready",
        "created_at": datetime.utcnow().isoformat() + "Z",
    }
    _write_meta(sdir, meta)
    return {
        "ok": True,
        "upload_session_id": sid,
        "chunk_size": chunk_size,
        "next_chunk": 0,
        "total_chunks": total_chunks,
        "file_size": file_size,
    }, 200


def upload_chunk(user: User) -> tuple[dict, int]:
    sid = (
        request.form.get("upload_session_id")
        or (request.get_json(silent=True) or {}).get("upload_session_id")
        or ""
    ).strip()
    sdir = _session_dir(sid)
    if sdir is None or not sdir.is_dir():
        return {"ok": False, "error": "session_not_found"}, 404
    meta = _read_meta(sdir)
    if not meta or int(meta.get("user_id") or 0) != int(user.id):
        return {"ok": False, "error": "forbidden"}, 403
    if meta.get("status") == "completed":
        return {
            "ok": True,
            "already_complete": True,
            "upload_session_id": sid,
            "server_media_id": meta.get("server_media_id"),
        }, 200

    try:
        chunk_number = int(request.form.get("chunk_number") or -1)
        total_chunks = int(
            request.form.get("total_chunks") or meta.get("total_chunks") or 0
        )
    except (TypeError, ValueError):
        return {"ok": False, "error": "chunk_number"}, 400
    if chunk_number < 0 or chunk_number >= max(total_chunks, 1):
        return {"ok": False, "error": "chunk_number"}, 400

    client_uuid = (request.form.get("client_uuid") or "").strip()
    if client_uuid and client_uuid != meta.get("client_uuid"):
        return {"ok": False, "error": "client_uuid_mismatch"}, 400

    chunk_checksum = (request.form.get("chunk_checksum") or "").strip().lower()
    uf = request.files.get("chunk") or request.files.get("file")
    if uf is None:
        return {"ok": False, "error": "chunk_missing"}, 400

    chunk_path = sdir / "chunks" / f"{chunk_number:05d}"
    # لا تعِد كتابة chunk مؤكد
    received = set(int(x) for x in (meta.get("received_chunks") or []))
    if chunk_number in received and chunk_path.is_file():
        next_chunk = 0
        while next_chunk in received:
            next_chunk += 1
        return {
            "ok": True,
            "duplicate_chunk": True,
            "chunk_number": chunk_number,
            "next_chunk": next_chunk,
            "received_count": len(received),
        }, 200

    h = hashlib.sha256()
    with chunk_path.open("wb") as out:
        while True:
            block = uf.stream.read(1024 * 1024)
            if not block:
                break
            h.update(block)
            out.write(block)
    digest = h.hexdigest()
    if chunk_checksum and chunk_checksum != digest:
        try:
            chunk_path.unlink(missing_ok=True)
        except Exception:
            pass
        return {"ok": False, "error": "chunk_checksum_mismatch"}, 400

    received.add(chunk_number)
    meta["received_chunks"] = sorted(received)
    meta["status"] = "uploading"
    _write_meta(sdir, meta)

    next_chunk = 0
    while next_chunk in received:
        next_chunk += 1
    return {
        "ok": True,
        "chunk_number": chunk_number,
        "chunk_checksum": digest,
        "next_chunk": next_chunk,
        "received_count": len(received),
        "total_chunks": int(meta.get("total_chunks") or total_chunks),
    }, 200


def upload_status(user: User) -> tuple[dict, int]:
    sid = (request.args.get("upload_session_id") or "").strip()
    sdir = _session_dir(sid)
    if sdir is None or not sdir.is_dir():
        return {"ok": False, "error": "session_not_found"}, 404
    meta = _read_meta(sdir)
    if not meta or int(meta.get("user_id") or 0) != int(user.id):
        return {"ok": False, "error": "forbidden"}, 403
    received = sorted(int(x) for x in (meta.get("received_chunks") or []))
    next_chunk = 0
    while next_chunk in received:
        next_chunk += 1
    chunk_size = int(meta.get("chunk_size") or DEFAULT_CHUNK_SIZE)
    uploaded_bytes = min(
        int(meta.get("file_size") or 0),
        len(received) * chunk_size,
    )
    # تقدير أدق لآخر جزء
    if received and max(received) == int(meta.get("total_chunks") or 1) - 1:
        uploaded_bytes = int(meta.get("file_size") or uploaded_bytes)
    return {
        "ok": True,
        "upload_session_id": sid,
        "status": meta.get("status"),
        "received_chunks": received,
        "next_chunk": next_chunk,
        "total_chunks": int(meta.get("total_chunks") or 0),
        "chunk_size": chunk_size,
        "file_size": int(meta.get("file_size") or 0),
        "uploaded_bytes": uploaded_bytes,
        "server_media_id": meta.get("server_media_id"),
    }, 200


def complete_upload(user: User, db: Session) -> tuple[dict, int]:
    data = request.get_json(silent=True) or {}
    sid = (data.get("upload_session_id") or "").strip()
    sdir = _session_dir(sid)
    if sdir is None or not sdir.is_dir():
        return {"ok": False, "error": "session_not_found"}, 404
    meta = _read_meta(sdir)
    if not meta or int(meta.get("user_id") or 0) != int(user.id):
        return {"ok": False, "error": "forbidden"}, 403

    if meta.get("status") == "completed" and meta.get("server_media_id"):
        return {
            "ok": True,
            "already_received": True,
            "server_media_id": int(meta["server_media_id"]),
            "client_uuid": meta.get("client_uuid"),
        }, 200

    total = int(meta.get("total_chunks") or 0)
    received = set(int(x) for x in (meta.get("received_chunks") or []))
    missing = [i for i in range(total) if i not in received]
    if missing:
        return {
            "ok": False,
            "error": "missing_chunks",
            "missing_chunks": missing[:50],
            "next_chunk": missing[0],
        }, 400

    assembled = sdir / "assembled.bin"
    with assembled.open("wb") as out:
        for i in range(total):
            cp = sdir / "chunks" / f"{i:05d}"
            if not cp.is_file():
                return {"ok": False, "error": "chunk_file_missing", "chunk": i}, 400
            with cp.open("rb") as inp:
                shutil.copyfileobj(inp, out, length=1024 * 1024)

    expected_size = int(meta.get("file_size") or 0)
    actual_size = assembled.stat().st_size
    if expected_size and actual_size != expected_size:
        return {
            "ok": False,
            "error": "size_mismatch",
            "expected": expected_size,
            "actual": actual_size,
        }, 400

    digest = _sha256_file(assembled)
    expected_cs = (meta.get("checksum") or "").strip().lower()
    if expected_cs and expected_cs != digest:
        return {
            "ok": False,
            "error": "checksum_mismatch",
            "expected": expected_cs,
            "actual": digest,
        }, 400

    free = _disk_free(EVAL_CRITERION_MEDIA_DIR)
    if free < actual_size + SERVER_FREE_MARGIN:
        return {
            "ok": False,
            "error": "INSUFFICIENT_SERVER_STORAGE",
            "code": "INSUFFICIENT_SERVER_STORAGE",
        }, 507

    media_kind = meta.get("media_kind") or "photo"
    mime = meta.get("mime_type") or ""
    client_uuid = meta.get("client_uuid") or ""
    rel = _final_relpath(
        exercise_id=int(meta.get("exercise_id") or 0),
        user_id=int(user.id),
        media_kind=media_kind,
        mime=mime,
        client_uuid=client_uuid or uuid.uuid4().hex,
    )

    try:
        row = persist_criterion_medium_from_path(
            db,
            exercise_id=int(meta.get("exercise_id") or 0),
            unit_level_key=meta.get("unit_level_key") or "",
            list_item_id=meta.get("evaluation_list_item_id"),
            bundle_action_eval_id=meta.get("bundle_action_eval_id"),
            row_index=int(meta.get("row_index") or 0),
            media_kind=media_kind,
            mime_type_in=mime,
            source_path=assembled,
            relpath=rel,
            uploaded_by_id=int(user.id),
            client_op_id=client_uuid,
            checksum=digest,
        )
        db.commit()
    except ValueError as err:
        db.rollback()
        tag = "".join(str(x) for x in err.args)
        if "mime" in tag:
            return {"ok": False, "error": "mime"}, 415
        return {"ok": False, "error": "reject", "detail": tag}, 400
    except Exception as e:
        db.rollback()
        return {"ok": False, "error": "persist_failed", "detail": str(e)}, 500

    meta["status"] = "completed"
    meta["server_media_id"] = int(row.id)
    meta["final_checksum"] = digest
    _write_meta(sdir, meta)

    # تنظيف الأجزاء (الإبقاء على meta للتكرار)
    try:
        chunks_dir = sdir / "chunks"
        if chunks_dir.is_dir():
            shutil.rmtree(chunks_dir, ignore_errors=True)
        if assembled.is_file():
            assembled.unlink(missing_ok=True)
    except Exception:
        pass

    return {
        "ok": True,
        "server_media_id": int(row.id),
        "client_uuid": client_uuid,
        "checksum": digest,
        "file_size": actual_size,
        "relpath": row.file_relpath,
    }, 200
