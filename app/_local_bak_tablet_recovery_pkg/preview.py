# -*- coding: utf-8 -*-
"""بناء معاينة الاستعادة — بدون تعديل نتائج التقييم أو الوسائط."""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.models.domain import (
    EvaluationListPdfItem,
    EvaluationListSavedResult,
    Exercise,
    TabletClientOp,
)
from app.models.user import User
from app.tablet_recovery.parser import (
    RecoveryPackage,
    count_notes,
    count_scored,
    parse_created_at,
    rows_fingerprint,
)
from app.tablet_recovery.targets import (
    remap_note,
    resolve_navigable_eval_item,
    unit_hints_from_package,
    unit_is_navigable,
)
from app.unit_levels_catalog import label_for_unit_level_key


STATUS_READY = "جاهز للاستعادة"
STATUS_EXISTS = "موجود مسبقاً"
STATUS_CONFLICT = "تعارض"
STATUS_APPROVED_CONFLICT = "تعارض مع قائمة معتمدة"
STATUS_MISSING_LIST = "قائمة غير موجودة"
STATUS_WRONG_EXERCISE = "تمرين غير مطابق"
STATUS_WRONG_JUDGE = "محكم غير مطابق"
STATUS_REVIEW = "يتطلب مراجعة"
STATUS_ALREADY_OP = "تم استلامها مسبقاً"
STATUS_CACHE_ONLY = "CACHE ONLY – MANUAL REVIEW REQUIRED"


def _payload_rows_from_saved(saved: EvaluationListSavedResult | None) -> list[dict]:
    if saved is None or not (saved.payload_json or "").strip():
        return []
    try:
        data = json.loads(saved.payload_json)
    except Exception:
        return []
    if not isinstance(data, dict):
        return []
    rows = data.get("rows")
    if not isinstance(rows, list):
        return []
    return [dict(r) for r in rows if isinstance(r, dict)]


def _server_state_label(saved: EvaluationListSavedResult | None, candidate_fp: str) -> str:
    if saved is None:
        return "لا توجد نتيجة"
    rows = _payload_rows_from_saved(saved)
    if not rows and not (saved.payload_json or "").strip():
        return "لا توجد نتيجة"
    server_fp = rows_fingerprint(rows)
    if bool(saved.is_approved):
        if candidate_fp and server_fp == candidate_fp:
            return "معتمدة ومطابقة"
        return "معتمدة ومختلفة"
    if candidate_fp and server_fp == candidate_fp:
        return "مطابقة"
    if rows:
        return "مختلفة"
    return "جزئية / فارغة"


def build_recovery_preview(db: Session, package: RecoveryPackage) -> dict[str, Any]:
    """يبني معاينة كاملة للمقارنة — قراءة فقط على بيانات التقييم."""
    manifest = package.manifest or {}
    exercise_id = manifest.get("exercise_id")
    try:
        exercise_id = int(exercise_id) if exercise_id is not None else None
    except Exception:
        exercise_id = None
    judge_id = manifest.get("judge_id") or manifest.get("user_id")
    try:
        judge_id = int(judge_id) if judge_id is not None else None
    except Exception:
        judge_id = None

    # Infer from pending if missing
    if exercise_id is None:
        for op in package.pending_ops:
            if op.exercise_id is not None:
                exercise_id = op.exercise_id
                break
    if judge_id is None:
        for op in package.pending_ops:
            if op.user_id is not None:
                judge_id = op.user_id
                break
            if op.judge_id is not None:
                judge_id = op.judge_id
                break

    exercise = db.get(Exercise, int(exercise_id)) if exercise_id else None
    judge = db.get(User, int(judge_id)) if judge_id else None
    unit_hints = unit_hints_from_package(package)

    # Group save_results by eval_item_id
    saves_by_item: dict[int, list] = {}
    for op in package.pending_ops:
        if not op.is_save_results:
            continue
        if op.eval_item_id is None:
            continue
        saves_by_item.setdefault(int(op.eval_item_id), []).append(op)

    for item_id, ops in saves_by_item.items():
        ops.sort(key=lambda o: (parse_created_at(o.created_at), o.id))

    cache_by_item: dict[int, list] = {}
    for c in package.cache_evals:
        if c.eval_item_id is None:
            continue
        cache_by_item.setdefault(int(c.eval_item_id), []).append(c)

    media_by_item: dict[int, list] = {}
    for m in package.media:
        iid = m.evaluation_list_item_id
        if iid is None:
            continue
        media_by_item.setdefault(int(iid), []).append(m)

    # لا نعرض مئات سجلات الـ cache الفارغة — فقط ما فيه عمل قابل للاستعادة
    all_item_ids = sorted(
        set(saves_by_item.keys())
        | set(media_by_item.keys())
        | {
            iid
            for iid, caches in cache_by_item.items()
            if any(count_scored(c.saved_rows) > 0 or c.locally_modified for c in caches)
        }
    )

    evaluations: list[dict[str, Any]] = []
    conflict_count = 0
    ready_count = 0

    for item_id in all_item_ids:
        save_ops = saves_by_item.get(item_id, [])
        caches = cache_by_item.get(item_id, [])
        media_rows = media_by_item.get(item_id, [])

        versions = []
        for idx, op in enumerate(save_ops, start=1):
            versions.append(
                {
                    "index": idx,
                    "pending_op_id": op.id,
                    "client_op_id": op.client_op_id,
                    "created_at": op.created_at,
                    "scored_rows": op.scored_count,
                    "notes": op.notes_count,
                    "rows_found": len(op.save_rows),
                    "body_parse_ok": op.body_parse_ok,
                    "sync_status": op.sync_status,
                    "malformed": not op.body_parse_ok,
                }
            )

        # Latest valid by chronology among parse-ok
        valid_ops = [o for o in save_ops if o.body_parse_ok and o.save_rows is not None]
        candidate = valid_ops[-1] if valid_ops else (save_ops[-1] if save_ops else None)
        if candidate and not candidate.body_parse_ok and valid_ops:
            candidate = valid_ops[-1]

        pending_rows = candidate.save_rows if candidate else []
        cache_rows = caches[0].saved_rows if caches else []
        pending_exists = bool(save_ops)
        cache_exists = bool(caches)

        if pending_exists and cache_exists:
            if rows_fingerprint(pending_rows) == rows_fingerprint(cache_rows):
                match_status = "MATCH"
            else:
                match_status = "SOURCE_MISMATCH"
        elif pending_exists:
            match_status = "PENDING_ONLY"
        elif cache_exists:
            match_status = "CACHE_ONLY"
        else:
            match_status = "MEDIA_ONLY"

        source = "PENDING_OP"
        if candidate is None and caches:
            source = "CACHE"
            pending_rows = cache_rows

        item = db.get(EvaluationListPdfItem, int(item_id))
        target_item = resolve_navigable_eval_item(
            db, item, hint_unit_keys=unit_hints.get(int(item_id), [])
        )
        list_title = ""
        unit_key = ""
        unit_label = ""
        redirect_note = None
        item_exercise_ok = True
        display_item_id = int(item_id)
        if item is None:
            status = STATUS_MISSING_LIST
            item_exercise_ok = False
        else:
            list_title = (getattr(item, "text", None) or "") or f"#{item_id}"
            if target_item is not None and int(target_item.id) != int(item.id):
                redirect_note = remap_note(item, target_item)
                display_item_id = int(target_item.id)
                unit_key = (target_item.unit_level_key or "").strip()
            else:
                unit_key = (item.unit_level_key or "").strip()
            unit_label = label_for_unit_level_key(unit_key, db=db) if unit_key else ""
            if not unit_label and unit_key and not unit_is_navigable(db, unit_key):
                unit_label = f"{unit_key} (غير ظاهرة في القائمة)"
            if exercise is not None and int(item.exercise_id) != int(exercise.id):
                status = STATUS_WRONG_EXERCISE
                item_exercise_ok = False
            elif exercise_id is not None and int(item.exercise_id) != int(exercise_id):
                status = STATUS_WRONG_EXERCISE
                item_exercise_ok = False
            # compare server state against TARGET (navigable) item
            compare_item = target_item or item
            item = compare_item  # use navigable item for subsequent server checks
            item_id_for_server = int(compare_item.id)
        # keep package item_id as eval_item_id for selection; store target separately
        package_item_id = int(item_id)
        server_item_id = (
            int(target_item.id)
            if target_item is not None
            else (int(item.id) if item is not None else package_item_id)
        )

        if exercise is None and exercise_id is not None:
            target_status_prefix = STATUS_WRONG_EXERCISE
        else:
            target_status_prefix = None

        if judge_id is not None and judge is None:
            judge_ok = False
        else:
            judge_ok = True

        # client_op duplicate
        already_op = False
        if candidate and candidate.client_op_id and judge_id:
            already_op = (
                db.query(TabletClientOp)
                .filter(
                    TabletClientOp.user_id == int(judge_id),
                    TabletClientOp.client_op_id == candidate.client_op_id,
                )
                .first()
                is not None
            )

        saved = None
        if item is not None and exercise is not None:
            saved = (
                db.query(EvaluationListSavedResult)
                .filter(
                    EvaluationListSavedResult.exercise_id == int(exercise.id),
                    EvaluationListSavedResult.evaluation_item_id == int(server_item_id),
                )
                .order_by(
                    EvaluationListSavedResult.updated_at.desc(),
                    EvaluationListSavedResult.id.desc(),
                )
                .first()
            )
            # إن وُجدت النتيجة على القائمة اليتيمة الأصلية فقط — اعتبرها موجودة للتحويل
            if saved is None and server_item_id != package_item_id:
                saved = (
                    db.query(EvaluationListSavedResult)
                    .filter(
                        EvaluationListSavedResult.exercise_id == int(exercise.id),
                        EvaluationListSavedResult.evaluation_item_id
                        == int(package_item_id),
                    )
                    .order_by(
                        EvaluationListSavedResult.updated_at.desc(),
                        EvaluationListSavedResult.id.desc(),
                    )
                    .first()
                )

        cand_fp = rows_fingerprint(pending_rows)
        server_label = _server_state_label(saved, cand_fp)

        # Decide status
        status = STATUS_READY
        default_selected = True
        if target_status_prefix:
            status = target_status_prefix
            default_selected = False
        elif not item_exercise_ok:
            status = STATUS_MISSING_LIST if item is None else STATUS_WRONG_EXERCISE
            default_selected = False
        elif not judge_ok:
            status = STATUS_WRONG_JUDGE
            default_selected = False
        elif match_status == "CACHE_ONLY":
            status = STATUS_CACHE_ONLY
            default_selected = False
        elif candidate is None:
            status = STATUS_REVIEW
            default_selected = False
        elif already_op:
            status = STATUS_ALREADY_OP
            default_selected = False
        elif saved is not None and bool(saved.is_approved):
            server_fp = rows_fingerprint(_payload_rows_from_saved(saved))
            if server_fp == cand_fp:
                status = STATUS_EXISTS
                default_selected = False
            else:
                status = STATUS_APPROVED_CONFLICT
                default_selected = False
                conflict_count += 1
        elif saved is not None:
            server_fp = rows_fingerprint(_payload_rows_from_saved(saved))
            if server_fp == cand_fp:
                status = STATUS_EXISTS
                default_selected = False
            else:
                status = STATUS_CONFLICT
                default_selected = False
                conflict_count += 1
        elif match_status == "SOURCE_MISMATCH":
            # still ready but flag review info
            status = STATUS_READY

        if status == STATUS_READY:
            ready_count += 1

        missing_media = sum(1 for m in media_rows if m.physical_path is None)

        # Approve ops for this item
        approve_ops = [
            op
            for op in package.pending_ops
            if op.op_type == "approve" and op.eval_item_id == item_id
        ]

        evaluations.append(
            {
                "eval_item_id": package_item_id,
                "target_eval_item_id": server_item_id,
                "list_title": list_title or f"#{package_item_id}",
                "unit_key": unit_key,
                "unit_label": unit_label,
                "redirect_note": redirect_note,
                "saved_versions": len(versions),
                "versions": versions,
                "latest_created_at": candidate.created_at if candidate else "",
                "scored_rows": count_scored(pending_rows),
                "notes_count": count_notes(pending_rows),
                "media_count": len(media_rows),
                "missing_media_count": missing_media,
                "source": source,
                "match_status": match_status,
                "pending_exists": pending_exists,
                "cache_exists": cache_exists,
                "pending_scored": count_scored(candidate.save_rows) if candidate else 0,
                "cache_scored": count_scored(cache_rows),
                "pending_notes": count_notes(candidate.save_rows) if candidate else 0,
                "cache_notes": count_notes(cache_rows),
                "server_state": server_label,
                "status": status,
                "default_selected": default_selected,
                "candidate_pending_op_id": candidate.id if candidate else None,
                "candidate_client_op_id": candidate.client_op_id if candidate else None,
                "candidate_rows": pending_rows,
                "has_approve_op": bool(approve_ops),
                "approve_created_at": approve_ops[-1].created_at if approve_ops else "",
                "recommended": "LATEST VALID SAVE" if candidate and candidate.body_parse_ok else "MANUAL REVIEW",
                "open_url": (
                    f"/admin/evaluation-lists/{unit_key}/view/{server_item_id}"
                    if unit_key
                    else f"/admin/evaluation-lists"
                ),
            }
        )

    other_ops = [
        {
            "id": op.id,
            "kind": op.kind,
            "op_type": op.op_type,
            "eval_item_id": op.eval_item_id,
            "created_at": op.created_at,
            "sync_status": op.sync_status,
        }
        for op in package.pending_ops
        if op.op_type not in ("save_results",)
    ]

    return {
        "manifest": {
            "device_id": manifest.get("device_id"),
            "app_version": manifest.get("app_version"),
            "export_timestamp": manifest.get("export_timestamp"),
            "exercise_id": exercise_id,
            "judge_id": judge_id,
            "user_id": manifest.get("user_id") or judge_id,
            "unit": manifest.get("unit") or manifest.get("unit_label") or "",
            "pending_operation_count": manifest.get("pending_operation_count")
            or len(package.pending_ops),
            "save_results_operation_count": manifest.get("save_results_operation_count")
            or sum(1 for o in package.pending_ops if o.is_save_results),
            "media_count": manifest.get("media_count") or len(package.media),
            "image_count": manifest.get("image_count"),
            "video_count": manifest.get("video_count"),
            "failed_operation_count": manifest.get("failed_operation_count"),
        },
        "server": {
            "exercise_found": exercise is not None,
            "exercise_title": (exercise.title if exercise is not None else None),
            "judge_found": judge is not None,
            "judge_name": (
                (getattr(judge, "full_name", None) or getattr(judge, "username", None))
                if judge is not None
                else None
            ),
        },
        "evaluations": evaluations,
        "other_ops": other_ops,
        "parse_warnings": list(package.parse_warnings),
        "summary": {
            "evaluation_count": len(evaluations),
            "ready_count": ready_count,
            "conflict_count": conflict_count,
            "media_count": len(package.media),
            "missing_media": sum(1 for m in package.media if m.physical_path is None),
            "has_excel": package.has_excel,
        },
    }
