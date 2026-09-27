"""استعادة بيانات تابلت المحكم من حزمة ZIP محلية — دون مزامنة الجهاز."""
from __future__ import annotations

import hashlib
import json
import shutil
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy.orm import Session

from app.paths import data_dir


def _ensure_iterable(value: Any, *, name: str) -> list[Any]:
    """Never iterate a bound method (e.g. dict.keys / form.getlist)."""
    if callable(value) and not isinstance(value, (list, tuple, str, bytes)):
        raise TypeError(f"{name} is a method; call it before iterating")
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    if isinstance(value, str):
        return [value] if value.strip() else []
    try:
        return list(value)
    except TypeError as exc:
        raise TypeError(f"{name} is not iterable") from exc


def selected_eval_item_ids(form) -> list[int]:
    raw = form.getlist("eval_item_id")
    out: list[int] = []
    for x in _ensure_iterable(raw, name="eval_item_id"):
        try:
            n = int(str(x).strip())
        except (TypeError, ValueError):
            continue
        if n > 0:
            out.append(n)
    return out


def parse_pending_body(raw_body: Any) -> dict[str, Any]:
    if isinstance(raw_body, dict):
        root = dict(raw_body)
    elif isinstance(raw_body, (bytes, bytearray)):
        raw_body = raw_body.decode("utf-8", errors="replace")
        root = None
    else:
        root = None
    if root is None:
        text = "" if raw_body is None else str(raw_body)
        if not text.strip():
            return {"parse_ok": False, "raw": text, "payload": {}, "rows": [], "client_op_id": ""}
        try:
            decoded = json.loads(text)
        except Exception:
            return {"parse_ok": False, "raw": text, "payload": {}, "rows": [], "client_op_id": ""}
        if not isinstance(decoded, dict):
            return {"parse_ok": False, "raw": text, "payload": {}, "rows": [], "client_op_id": ""}
        root = dict(decoded)
        raw_keep = text
    else:
        raw_keep = json.dumps(root, ensure_ascii=False)
    payload = root.get("payload") if isinstance(root.get("payload"), dict) else root
    rows_raw = payload.get("rows") if isinstance(payload, dict) else None
    rows: list[dict[str, Any]] = []
    for item in _ensure_iterable(rows_raw, name="payload.rows"):
        if isinstance(item, dict):
            rows.append(dict(item))
    return {
        "parse_ok": True,
        "raw": raw_keep,
        "payload": payload if isinstance(payload, dict) else {},
        "rows": rows,
        "client_op_id": str(root.get("client_op_id") or ""),
    }


def _row_has_score(row: dict[str, Any]) -> bool:
    return str(row.get("acquired") or "").strip() != ""


def _row_has_notes(row: dict[str, Any]) -> bool:
    return str(row.get("notes") or "").strip() != ""


def _rows_fingerprint(rows: Iterable[dict[str, Any]]) -> str:
    parts: list[str] = []
    for r in _ensure_iterable(rows, name="rows"):
        if not isinstance(r, dict):
            continue
        parts.append(
            "|".join(
                [
                    str(r.get("row_kind") or "").strip(),
                    str(r.get("element") or "").strip(),
                    str(r.get("max_val") or "").strip(),
                    str(r.get("acquired") or "").strip(),
                    str(r.get("notes") or "").strip(),
                ]
            )
        )
    return "\n".join(parts)


def _cache_eval_id(cache_key: str) -> int | None:
    parts = str(cache_key or "").split(":")
    if not parts:
        return None
    last = parts[-1].strip()
    if not last.isdigit():
        return None
    if "evaluation_list_detail" in cache_key:
        return int(last)
    return None


def _cache_rows(entry: dict[str, Any]) -> list[dict[str, Any]]:
    body = entry.get("json_body")
    parsed: dict[str, Any] = {}
    if isinstance(body, dict):
        parsed = body
    elif isinstance(body, str) and body.strip():
        try:
            decoded = json.loads(body)
            if isinstance(decoded, dict):
                parsed = decoded
        except Exception:
            parsed = {}
    rows = parsed.get("saved_rows")
    if not isinstance(rows, list):
        payload = parsed.get("saved_payload")
        if isinstance(payload, dict) and isinstance(payload.get("rows"), list):
            rows = payload.get("rows")
    out: list[dict[str, Any]] = []
    for item in _ensure_iterable(rows, name="cache.saved_rows"):
        if isinstance(item, dict):
            out.append(dict(item))
    return out


@dataclass
class RecoveryItem:
    eval_item_id: int
    title: str
    pending_copy: bool
    cache_copy: bool
    source_mismatch: bool
    rows: list[dict[str, Any]] = field(default_factory=list)
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    media_count: int = 0
    pending_op_id: str = ""
    sync_status: str = ""

    @property
    def ready(self) -> bool:
        return self.pending_copy

    @property
    def status_ar(self) -> str:
        if self.pending_copy:
            return "جاهز للاستعادة"
        if self.cache_copy:
            return "CACHE ONLY – MANUAL REVIEW REQUIRED"
        return "—"

    @property
    def source_label(self) -> str:
        if self.pending_copy and self.cache_copy:
            return "PENDING_OP / SOURCE_MISMATCH" if self.source_mismatch else "PENDING_OP / BOTH"
        if self.pending_copy:
            return "PENDING_OP"
        if self.cache_copy:
            return "CACHE / CACHE_ONLY"
        return "—"

    @property
    def recovery_status(self) -> str:
        if self.source_mismatch:
            return "SOURCE_MISMATCH"
        if self.pending_copy and self.cache_copy:
            return "BOTH"
        if self.pending_copy:
            return "PENDING_ONLY"
        if self.cache_copy:
            return "CACHE_ONLY"
        return "NONE"

    @property
    def score_count(self) -> int:
        return sum(1 for r in self.rows if _row_has_score(r))

    @property
    def notes_count(self) -> int:
        return sum(1 for r in self.rows if _row_has_notes(r))


@dataclass
class RecoveryPreview:
    zip_hash: str
    extract_dir: str
    zip_name: str
    device_id: str = ""
    app_version: str = ""
    export_timestamp: str = ""
    exercise_id: int | None = None
    judge_id: int | None = None
    user_id: int | None = None
    judge_name: str = ""
    unit: str = ""
    pending_operations: int = 0
    save_results_operations: int = 0
    media_count: int = 0
    ready_count: int = 0
    mismatch_count: int = 0
    missing_media: int = 0
    items: list[RecoveryItem] = field(default_factory=list)
    previously_applied: dict[str, str] | None = None


def _uploads_root() -> Path:
    p = data_dir() / "tablet_recovery_uploads"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _applied_path() -> Path:
    return data_dir() / "tablet_recovery_applied.json"


def load_applied_packages() -> dict[str, Any]:
    path = _applied_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def record_applied_package(zip_hash: str, meta: dict[str, Any]) -> None:
    data = load_applied_packages()
    data[zip_hash] = meta
    _applied_path().write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def extract_recovery_zip(zip_path: Path, dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(dest)


def _read_json(path: Path) -> Any:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def build_preview(extract_dir: Path, *, zip_hash: str, zip_name: str) -> RecoveryPreview:
    manifest = _read_json(extract_dir / "manifest.json") or {}
    if not isinstance(manifest, dict):
        manifest = {}
    pending_doc = _read_json(extract_dir / "data" / "pending_ops.json") or {}
    cache_doc = _read_json(extract_dir / "data" / "cache_evaluations.json") or {}
    media_doc = _read_json(extract_dir / "data" / "media_manifest.json") or {}

    ops_raw = pending_doc.get("operations") if isinstance(pending_doc, dict) else pending_doc
    ops = [o for o in _ensure_iterable(ops_raw, name="pending_ops") if isinstance(o, dict)]
    cache_entries = []
    if isinstance(cache_doc, dict):
        cache_entries = [
            e for e in _ensure_iterable(cache_doc.get("entries"), name="cache.entries") if isinstance(e, dict)
        ]
    media_records = []
    if isinstance(media_doc, dict):
        media_records = [
            m for m in _ensure_iterable(media_doc.get("records"), name="media.records") if isinstance(m, dict)
        ]

    save_ops = [
        o
        for o in ops
        if str(o.get("op_type") or "") == "save_results"
        or "save-results" in str(o.get("path") or "")
    ]

    pending_by_eval: dict[int, dict[str, Any]] = {}
    for o in save_ops:
        eid = o.get("eval_item_id")
        try:
            eid_n = int(eid) if eid is not None else 0
        except (TypeError, ValueError):
            eid_n = 0
        if eid_n <= 0:
            parsed = parse_pending_body(o.get("body"))
            payload = parsed.get("payload") or {}
            try:
                eid_n = int(payload.get("eval_item_id") or o.get("list_id") or 0)
            except (TypeError, ValueError):
                eid_n = 0
        if eid_n > 0 and eid_n not in pending_by_eval:
            pending_by_eval[eid_n] = o

    cache_by_eval: dict[int, dict[str, Any]] = {}
    for e in cache_entries:
        eid = _cache_eval_id(str(e.get("cache_key") or ""))
        if eid and eid not in cache_by_eval:
            cache_by_eval[eid] = e

    media_by_eval: dict[int, int] = {}
    missing_media = 0
    for m in media_records:
        exists = str(m.get("file_exists") or "").upper() == "YES"
        if not exists:
            missing_media += 1
        eid = m.get("evaluation_list_item_id")
        try:
            eid_n = int(eid) if eid is not None else 0
        except (TypeError, ValueError):
            eid_n = 0
        if eid_n > 0:
            media_by_eval[eid_n] = media_by_eval.get(eid_n, 0) + 1

    item_ids = sorted(set(pending_by_eval.keys()) | set(cache_by_eval.keys()))
    items: list[RecoveryItem] = []
    for eid in item_ids:
        pop = pending_by_eval.get(eid)
        centry = cache_by_eval.get(eid)
        parsed = parse_pending_body(pop.get("body") if pop else "")
        p_rows = parsed["rows"] if pop else []
        c_rows = _cache_rows(centry) if centry else []
        mismatch = bool(pop and centry and _rows_fingerprint(p_rows) != _rows_fingerprint(c_rows))
        rows = p_rows if pop else c_rows
        payload = parsed["payload"] if pop else {}
        items.append(
            RecoveryItem(
                eval_item_id=eid,
                title="",
                pending_copy=pop is not None,
                cache_copy=centry is not None,
                source_mismatch=mismatch,
                rows=rows,
                payload=payload if isinstance(payload, dict) else {},
                created_at=str((pop or {}).get("created_at") or (centry or {}).get("updated_at") or ""),
                media_count=media_by_eval.get(eid, 0),
                pending_op_id=str((pop or {}).get("id") or ""),
                sync_status=str((pop or {}).get("sync_status") or (centry or {}).get("sync_status") or ""),
            )
        )

    applied = load_applied_packages().get(zip_hash)
    if not isinstance(applied, dict):
        applied = None

    def _int_or_none(v: Any) -> int | None:
        try:
            n = int(v)
            return n if n else None
        except (TypeError, ValueError):
            return None

    preview = RecoveryPreview(
        zip_hash=zip_hash,
        extract_dir=str(extract_dir),
        zip_name=zip_name,
        device_id=str(manifest.get("device_id") or ""),
        app_version=str(manifest.get("app_version") or ""),
        export_timestamp=str(manifest.get("export_timestamp") or ""),
        exercise_id=_int_or_none(manifest.get("exercise_id")),
        judge_id=_int_or_none(manifest.get("judge_id")),
        user_id=_int_or_none(manifest.get("user_id")),
        judge_name=str(manifest.get("judge_name") or ""),
        unit=str(manifest.get("unit") or ""),
        pending_operations=len(ops),
        save_results_operations=len(save_ops),
        media_count=len(media_records),
        ready_count=sum(1 for i in items if i.ready),
        mismatch_count=sum(1 for i in items if i.source_mismatch),
        missing_media=missing_media,
        items=items,
        previously_applied=applied,
    )
    return preview


def attach_item_titles(db: Session, preview: RecoveryPreview) -> None:
    from app.models import EvaluationListPdfItem, User

    ids = [i.eval_item_id for i in preview.items]
    if ids:
        rows = (
            db.query(EvaluationListPdfItem)
            .filter(EvaluationListPdfItem.id.in_(ids))
            .all()
        )
        titles = {int(r.id): (r.text or "").strip() for r in rows}
        for item in preview.items:
            item.title = titles.get(item.eval_item_id, "")
    if not preview.judge_name and preview.judge_id:
        u = db.get(User, int(preview.judge_id))
        if u is not None:
            preview.judge_name = (
                getattr(u, "full_name", None)
                or getattr(u, "username", "")
                or ""
            )


def _write_saved_result(
    db: Session,
    *,
    exercise_id: int,
    item,
    judge_id: int | None,
    payload: dict[str, Any],
) -> None:
    from app.evaluation_list_columns import merge_eval_narrative_into_payload
    from app.evaluation_workflow import apply_other_judge_overwrite, eval_judge_can_edit
    from app.exercise_phase_catalog import normalize_exercise_phase
    from app.models import EvaluationListSavedResult
    from app.views import (
        _evaluation_canonical_saved_row,
        _evaluation_delete_duplicate_saves,
        _evaluation_grade_from_payload_rows,
        _normalized_exercise_phase,
    )

    rows = payload.get("rows") if isinstance(payload.get("rows"), list) else []
    total_pct, grade = _evaluation_grade_from_payload_rows(
        [r for r in rows if isinstance(r, dict)]
    )
    saved = _evaluation_canonical_saved_row(db, exercise_id, int(item.id))
    if saved is not None and not eval_judge_can_edit(saved):
        apply_other_judge_overwrite(saved)
    if saved is None:
        saved = EvaluationListSavedResult(
            evaluation_item_id=int(item.id),
            exercise_id=int(exercise_id),
            exercise_phase=_normalized_exercise_phase(getattr(item, "exercise_phase", None)),
            unit_level_key=item.unit_level_key or "",
            saved_by_id=judge_id,
            is_approved=False,
        )
        db.add(saved)
    saved.payload_json = json.dumps(
        merge_eval_narrative_into_payload(payload, saved.payload_json),
        ensure_ascii=False,
    )
    saved.total_pct = total_pct
    saved.grade_label = grade
    if judge_id:
        saved.saved_by_id = judge_id
    saved.unit_level_key = item.unit_level_key or saved.unit_level_key or ""
    saved.exercise_phase = _normalized_exercise_phase(
        getattr(item, "exercise_phase", None) or normalize_exercise_phase(None)
    )
    db.flush()
    _evaluation_delete_duplicate_saves(
        db,
        exercise_id=int(exercise_id),
        evaluation_item_id=int(item.id),
        keep_id=saved.id,
    )


def _import_media_for_item(
    db: Session,
    *,
    extract_dir: Path,
    exercise_id: int,
    item,
    judge_id: int | None,
    eval_item_id: int,
) -> int:
    from app.eval_criterion_media import (
        ALLOWED_PHOTO_TYPES,
        ALLOWED_VIDEO_TYPES,
        persist_criterion_medium,
    )

    media_doc = _read_json(extract_dir / "data" / "media_manifest.json") or {}
    records = []
    if isinstance(media_doc, dict):
        records = [
            m
            for m in _ensure_iterable(media_doc.get("records"), name="media.records")
            if isinstance(m, dict)
        ]
    n = 0
    for rec in records:
        try:
            eid = int(rec.get("evaluation_list_item_id") or 0)
        except (TypeError, ValueError):
            eid = 0
        if eid != int(eval_item_id):
            continue
        rel = str(rec.get("exported_path") or "").replace("\\", "/").lstrip("/")
        if not rel:
            continue
        src = extract_dir / rel
        if not src.is_file():
            continue
        try:
            row_index = int(rec.get("row_index") or 0)
        except (TypeError, ValueError):
            row_index = 0
        kind = str(rec.get("media_kind") or "photo")
        mime = str(rec.get("mime_type") or "").split(";")[0].strip().lower()
        if "video" in kind.lower():
            if mime not in ALLOWED_VIDEO_TYPES:
                mime = "video/mp4"
        else:
            if mime not in ALLOWED_PHOTO_TYPES:
                mime = "image/jpeg"
        client_uuid = str(rec.get("client_uuid") or rec.get("id") or "")
        persist_criterion_medium(
            db,
            exercise_id=int(exercise_id),
            unit_level_key=item.unit_level_key or "",
            list_item_id=int(item.id),
            bundle_action_eval_id=None,
            row_index=row_index,
            media_kind=kind,
            mime_type_in=mime,
            bin_data=src.read_bytes(),
            uploaded_by_id=judge_id,
            client_op_id=client_uuid,
        )
        n += 1
    return n


def apply_recovery(
    db: Session,
    preview: RecoveryPreview,
    selected_ids: list[int],
    *,
    force: bool = False,
) -> dict[str, int]:
    from app.models import EvaluationListPdfItem, Exercise, User
    from app.views import _current_workspace_exercise

    if preview.previously_applied and not force:
        restored = preview.previously_applied.get("restored_at") or ""
        applied = preview.previously_applied.get("applied_at") or ""
        raise RuntimeError(
            "تم استخدام هذه الحزمة سابقاً — "
            f"restored: {restored} / applied: {applied}. "
            "يمنع الحماية دون إعادة تطبيق ثاني."
        )

    user = None
    if preview.judge_id:
        user = db.get(User, int(preview.judge_id))
    ex = db.get(Exercise, int(preview.exercise_id or 0)) if preview.exercise_id else None
    if ex is None:
        ex = _current_workspace_exercise(db, user) if user is not None else None
    if ex is None:
        ex = db.query(Exercise).order_by(Exercise.id.desc()).first()
    if ex is None:
        raise RuntimeError("لا يوجد تمرين لاستعادة النتائج إليه.")

    wanted = {int(x) for x in selected_ids if int(x) > 0}
    if not wanted:
        raise RuntimeError("لم يُحدد أي عنصر جاهز للاستعادة.")

    by_id = {i.eval_item_id: i for i in preview.items}
    extract_dir = Path(preview.extract_dir)
    restored = 0
    media_n = 0
    for eid in wanted:
        rec = by_id.get(eid)
        if rec is None or not rec.ready:
            continue
        item = db.get(EvaluationListPdfItem, int(eid))
        if item is None:
            from app.eval_identity_matcher import SourceIdentity, match_evaluation

            src = SourceIdentity(
                exercise_id=int(ex.id),
                eval_item_id=int(eid),
                unit_id="",
                unit_name="",
                evaluation_list_name=rec.title or "",
                judge_id=preview.judge_id,
                device_id=preview.device_id,
                client_op_id=str(rec.client_op_id or ""),
            )
            matched = match_evaluation(
                db, src, current_exercise_id=int(ex.id)
            )
            if matched.target is not None and matched.status in (
                "MATCHED_EXACT",
                "MATCHED_BY_UNIT_LIST",
                "MATCHED_BY_CONTEXT",
            ):
                item = db.get(EvaluationListPdfItem, int(matched.target.eval_item_id))
            if item is None:
                raise RuntimeError(
                    f"عنصر التقييم #{eid} غير موجود — استخدم استيراد Excel للمطابقة اليدوية."
                )
        payload = rec.payload if isinstance(rec.payload, dict) else {}
        if "rows" not in payload:
            payload = dict(payload)
            payload["rows"] = rec.rows
        _write_saved_result(
            db,
            exercise_id=int(ex.id),
            item=item,
            judge_id=preview.judge_id,
            payload=payload,
        )
        media_n += _import_media_for_item(
            db,
            extract_dir=extract_dir,
            exercise_id=int(ex.id),
            item=item,
            judge_id=preview.judge_id,
            eval_item_id=eid,
        )
        restored += 1

    if restored <= 0:
        raise RuntimeError("لا توجد عناصر جاهزة ضمن التحديد.")
    db.commit()
    now = datetime.utcnow().isoformat()
    record_applied_package(
        preview.zip_hash,
        {
            "restored_at": now,
            "applied_at": now,
            "device_id": preview.device_id,
            "restored_count": restored,
        },
    )
    return {"restored": restored, "media": media_n}
