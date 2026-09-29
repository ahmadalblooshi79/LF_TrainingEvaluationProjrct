# -*- coding: utf-8 -*-
"""تطبيق استعادة التقييمات والوسائط — استدعاء منطق داخلي موثوق."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.eval_criterion_media import mime_base, persist_criterion_medium_from_path
from app.evaluation_list_columns import (
    merge_eval_narrative_into_payload,
    payload_rows_missing_required_notes,
)
from app.evaluation_workflow import (
    apply_judge_save_after_reopen,
    apply_other_judge_overwrite,
    eval_judge_can_edit,
    eval_reopened_for_judge,
)
from app.models.domain import (
    EvaluationCriterionMedia,
    EvaluationListPdfItem,
    EvaluationListSavedResult,
    Exercise,
    TabletClientOp,
)
from app.models.user import User
from app.tablet_recovery.parser import RecoveryPackage, parse_created_at
from app.tablet_recovery.targets import (
    resolve_navigable_eval_item,
    unit_hints_from_package,
)


def _evaluation_grade_from_payload_save_safe(rows: list) -> tuple[float | None, str]:
    from app.views import _evaluation_grade_from_payload_rows

    return _evaluation_grade_from_payload_rows(rows)


def _delete_duplicate_saves(
    db: Session, *, exercise_id: int, evaluation_item_id: int, keep_id: int
) -> None:
    db.query(EvaluationListSavedResult).filter(
        EvaluationListSavedResult.exercise_id == exercise_id,
        EvaluationListSavedResult.evaluation_item_id == evaluation_item_id,
        EvaluationListSavedResult.id != keep_id,
    ).delete(synchronize_session=False)


def apply_evaluation_payload(
    db: Session,
    *,
    judge: User,
    item: EvaluationListPdfItem,
    exercise: Exercise,
    payload: dict[str, Any],
    allow_overwrite_unapproved: bool = True,
) -> EvaluationListSavedResult:
    """نسخة داخلية من منطق الحفظ بدون abort/commit — يرفع ValueError عند الرفض."""
    rows = payload.get("rows") or []
    if not isinstance(rows, list):
        raise ValueError("صفوف غير صالحة")
    if payload_rows_missing_required_notes(rows):
        raise ValueError(
            "لا يمكن الحفظ: يوجد بند نتيجته «مقبول» أو «راسب» بدون ملاحظات"
        )
    total_pct, grade = _evaluation_grade_from_payload_save_safe(rows)
    saved = (
        db.query(EvaluationListSavedResult)
        .filter(
            EvaluationListSavedResult.exercise_id == int(exercise.id),
            EvaluationListSavedResult.evaluation_item_id == int(item.id),
        )
        .order_by(
            EvaluationListSavedResult.updated_at.desc(),
            EvaluationListSavedResult.id.desc(),
        )
        .first()
    )
    if saved is not None and bool(saved.is_approved):
        raise ValueError("القائمة معتمدة على السيرفر — لن تُستبدل تلقائياً")
    if saved is not None and not eval_judge_can_edit(saved):
        if allow_overwrite_unapproved:
            apply_other_judge_overwrite(saved)
        else:
            raise ValueError("لا يمكن تعديل نتيجة محكم آخر")
    was_reopened = eval_reopened_for_judge(saved) if saved is not None else False
    if saved is None:
        from app.models.domain import ExercisePhase

        phase = getattr(item, "exercise_phase", None) or ExercisePhase.PREPARATION.value
        saved = EvaluationListSavedResult(
            evaluation_item_id=int(item.id),
            exercise_id=int(exercise.id),
            exercise_phase=str(phase),
            unit_level_key=item.unit_level_key or "",
            saved_by_id=int(judge.id),
            is_approved=False,
        )
        db.add(saved)
    saved.payload_json = json.dumps(
        merge_eval_narrative_into_payload(payload, saved.payload_json),
        ensure_ascii=False,
    )
    saved.total_pct = total_pct
    saved.grade_label = grade
    saved.saved_by_id = int(judge.id)
    if was_reopened:
        apply_judge_save_after_reopen(saved)
    db.flush()
    _delete_duplicate_saves(
        db,
        exercise_id=int(exercise.id),
        evaluation_item_id=int(item.id),
        keep_id=int(saved.id),
    )
    return saved


def _record_client_op(
    db: Session,
    *,
    user_id: int,
    client_op_id: str,
    op_type: str,
    path: str,
    response_body: dict,
    exercise_id: int | None,
) -> None:
    if not client_op_id:
        return
    existing = (
        db.query(TabletClientOp)
        .filter(
            TabletClientOp.user_id == int(user_id),
            TabletClientOp.client_op_id == client_op_id,
        )
        .first()
    )
    if existing is not None:
        return
    db.add(
        TabletClientOp(
            user_id=int(user_id),
            exercise_id=exercise_id,
            client_op_id=client_op_id[:120],
            op_type=(op_type or "")[:64],
            path=(path or "")[:400],
            response_json=json.dumps(response_body or {}, ensure_ascii=False),
        )
    )


def _media_already_on_server(
    db: Session,
    *,
    judge_id: int,
    exercise_id: int,
    list_item_id: int,
    client_key: str,
    checksum: str,
) -> EvaluationCriterionMedia | None:
    if client_key:
        by_client = (
            db.query(EvaluationCriterionMedia)
            .filter(
                EvaluationCriterionMedia.uploaded_by_id == int(judge_id),
                EvaluationCriterionMedia.client_op_id == client_key[:120],
            )
            .first()
        )
        if by_client is not None:
            return by_client
        by_scope = (
            db.query(EvaluationCriterionMedia)
            .filter(
                EvaluationCriterionMedia.exercise_id == int(exercise_id),
                EvaluationCriterionMedia.evaluation_list_item_id == int(list_item_id),
                EvaluationCriterionMedia.client_op_id == client_key[:120],
            )
            .first()
        )
        if by_scope is not None:
            return by_scope
    _ = checksum
    return None


def _restore_media_for_item(
    db: Session,
    *,
    judge: User,
    exercise: Exercise,
    item: EvaluationListPdfItem,
    media_rows: list,
) -> dict[str, Any]:
    """استعادة وسائط قائمة واحدة — آمن للتكرار (idempotent)."""
    ok = 0
    missing = 0
    skipped_existing = 0
    images = 0
    videos = 0
    errors: list[str] = []
    for m in media_rows:
        client_key = (m.client_uuid or m.id or "").strip()
        existing = _media_already_on_server(
            db,
            judge_id=int(judge.id),
            exercise_id=int(exercise.id),
            list_item_id=int(item.id),
            client_key=client_key,
            checksum=(m.checksum or ""),
        )
        if existing is not None:
            skipped_existing += 1
            continue
        if m.physical_path is None or not Path(m.physical_path).is_file():
            missing += 1
            errors.append(
                f"ملف مفقود: {m.export_relative_path or m.local_filename or m.id}"
            )
            continue
        mime = mime_base(m.mime_type) or (
            "video/mp4"
            if (m.media_kind or "").lower() == "video"
            else "image/jpeg"
        )
        try:
            persist_criterion_medium_from_path(
                db,
                exercise_id=int(exercise.id),
                unit_level_key=item.unit_level_key or "",
                list_item_id=int(item.id),
                bundle_action_eval_id=(
                    int(m.bundle_action_eval_id)
                    if m.bundle_action_eval_id is not None
                    else None
                ),
                row_index=int(m.row_index),
                media_kind=m.media_kind or "photo",
                mime_type_in=mime,
                source_path=Path(m.physical_path),
                relpath="",
                uploaded_by_id=int(judge.id),
                client_op_id=client_key[:120],
                checksum=(m.checksum or ""),
            )
            ok += 1
            if (m.media_kind or "").lower() == "video":
                videos += 1
            else:
                images += 1
            if client_key:
                _record_client_op(
                    db,
                    user_id=int(judge.id),
                    client_op_id=client_key[:120],
                    op_type="recovery_media_upload",
                    path="/recovery/media",
                    response_body={"ok": True, "recovered": True},
                    exercise_id=int(exercise.id),
                )
        except Exception as exc:
            missing += 1
            errors.append(f"{m.local_filename or m.id}: {exc}")
    return {
        "media_restored": ok,
        "media_missing": missing,
        "media_skipped_existing": skipped_existing,
        "images_restored": images,
        "videos_restored": videos,
        "media_errors": errors[:20],
    }


def restore_selected_evaluations(
    db: Session,
    package: RecoveryPackage,
    preview: dict[str, Any],
    *,
    selected_item_ids: list[int],
    restore_approvals: bool = False,
) -> dict[str, Any]:
    """
    يستعيد التقييمات المحددة داخل معاملة واحدة.
    إذا كانت النتائج موجودة مسبقاً يُتخطّى الحفظ لكن تُستعاد الوسائط الناقصة.
    """
    _ = restore_approvals
    selected = {int(x) for x in selected_item_ids}
    eval_map = {int(e["eval_item_id"]): e for e in preview.get("evaluations") or []}
    exercise_id = preview.get("manifest", {}).get("exercise_id")
    judge_id = preview.get("manifest", {}).get("judge_id")
    if exercise_id is None or judge_id is None:
        raise ValueError("معرّف التمرين أو المحكم مفقود من المعاينة")
    exercise = db.get(Exercise, int(exercise_id))
    judge = db.get(User, int(judge_id))
    if exercise is None:
        raise ValueError("التمرين غير موجود على السيرفر")
    if judge is None:
        raise ValueError("المحكم غير موجود على السيرفر")

    saves = {op.id: op for op in package.pending_ops if op.is_save_results}
    media_by_item: dict[int, list] = {}
    for m in package.media:
        if m.evaluation_list_item_id is None:
            continue
        media_by_item.setdefault(int(m.evaluation_list_item_id), []).append(m)
    unit_hints = unit_hints_from_package(package)

    results: list[dict[str, Any]] = []
    restored_eval = 0
    skipped = 0
    conflicts = 0
    restored_media = 0
    missing_media = 0
    images_restored = 0
    videos_restored = 0

    try:
        for item_id in sorted(selected):
            row = eval_map.get(item_id)
            if row is None:
                results.append(
                    {
                        "eval_item_id": item_id,
                        "ok": False,
                        "status": "غير موجود في المعاينة",
                    }
                )
                skipped += 1
                continue
            if row.get("status") in (
                "تعارض مع قائمة معتمدة",
                "قائمة غير موجودة",
                "تمرين غير مطابق",
                "محكم غير مطابق",
            ):
                results.append(
                    {
                        "eval_item_id": item_id,
                        "ok": False,
                        "status": row.get("status"),
                    }
                )
                conflicts += 1
                continue
            if row.get("status") == "CACHE ONLY – MANUAL REVIEW REQUIRED":
                results.append(
                    {
                        "eval_item_id": item_id,
                        "ok": False,
                        "status": row.get("status"),
                    }
                )
                skipped += 1
                continue

            source_item = db.get(EvaluationListPdfItem, int(item_id))
            if source_item is None or int(source_item.exercise_id) != int(exercise.id):
                results.append(
                    {
                        "eval_item_id": item_id,
                        "ok": False,
                        "status": "قائمة غير موجودة",
                    }
                )
                conflicts += 1
                continue

            # وجّه إلى قائمة قابلة للتصفح إن كانت الوحدة يتيمة
            target_id = row.get("target_eval_item_id") or item_id
            item = db.get(EvaluationListPdfItem, int(target_id))
            if item is None:
                item = resolve_navigable_eval_item(
                    db,
                    source_item,
                    hint_unit_keys=unit_hints.get(int(item_id), []),
                ) or source_item
            elif int(item.id) != int(source_item.id):
                pass
            else:
                item = (
                    resolve_navigable_eval_item(
                        db,
                        source_item,
                        hint_unit_keys=unit_hints.get(int(item_id), []),
                    )
                    or source_item
                )
            skip_save = row.get("status") in (
                "موجود مسبقاً",
                "تم استلامها مسبقاً",
            )

            saved_now = (
                db.query(EvaluationListSavedResult)
                .filter(
                    EvaluationListSavedResult.exercise_id == int(exercise.id),
                    EvaluationListSavedResult.evaluation_item_id == int(item.id),
                )
                .order_by(
                    EvaluationListSavedResult.updated_at.desc(),
                    EvaluationListSavedResult.id.desc(),
                )
                .first()
            )
            if saved_now is not None and bool(saved_now.is_approved) and not skip_save:
                results.append(
                    {
                        "eval_item_id": item_id,
                        "ok": False,
                        "status": "تعارض مع قائمة معتمدة",
                    }
                )
                conflicts += 1
                continue

            # إن كانت النتائج على القائمة اليتيمة والهدف فارغ — انقلها للهدف القابل للتصفح
            remapped_orphan = False
            if int(item.id) != int(source_item.id):
                orphan_saved = (
                    db.query(EvaluationListSavedResult)
                    .filter(
                        EvaluationListSavedResult.exercise_id == int(exercise.id),
                        EvaluationListSavedResult.evaluation_item_id
                        == int(source_item.id),
                    )
                    .order_by(
                        EvaluationListSavedResult.updated_at.desc(),
                        EvaluationListSavedResult.id.desc(),
                    )
                    .first()
                )
                if orphan_saved is not None and saved_now is None:
                    orphan_saved.evaluation_item_id = int(item.id)
                    orphan_saved.unit_level_key = item.unit_level_key or ""
                    db.flush()
                    saved_now = orphan_saved
                    remapped_orphan = True
                for mrow in (
                    db.query(EvaluationCriterionMedia)
                    .filter(
                        EvaluationCriterionMedia.evaluation_list_item_id
                        == int(source_item.id)
                    )
                    .all()
                ):
                    mrow.evaluation_list_item_id = int(item.id)
                    mrow.unit_level_key = item.unit_level_key or ""
                db.flush()

            results_applied = remapped_orphan
            if not skip_save:
                op_id = row.get("candidate_pending_op_id")
                op = saves.get(op_id) if op_id else None
                if op is None:
                    candidates = [
                        o
                        for o in package.pending_ops
                        if o.is_save_results
                        and o.eval_item_id == item_id
                        and o.body_parse_ok
                    ]
                    candidates.sort(key=lambda o: (parse_created_at(o.created_at), o.id))
                    op = candidates[-1] if candidates else None
                if op is None or not op.body_parse_ok:
                    if not media_by_item.get(item_id) and not remapped_orphan:
                        results.append(
                            {
                                "eval_item_id": item_id,
                                "ok": False,
                                "status": "لا مرشح حفظ صالح",
                            }
                        )
                        skipped += 1
                        continue
                    skip_save = True
                else:
                    if op.client_op_id:
                        existing_op = (
                            db.query(TabletClientOp)
                            .filter(
                                TabletClientOp.user_id == int(judge.id),
                                TabletClientOp.client_op_id == op.client_op_id,
                            )
                            .first()
                        )
                        if existing_op is not None:
                            skip_save = True

                    if not skip_save:
                        payload: dict[str, Any] = {}
                        if isinstance(op.body, dict):
                            if isinstance(op.body.get("payload"), dict):
                                payload = dict(op.body["payload"])
                            else:
                                payload = {
                                    "rows": op.save_rows,
                                    "dilemma_description": op.body.get(
                                        "dilemma_description", ""
                                    ),
                                    "dilemma_requirements": op.body.get(
                                        "dilemma_requirements", ""
                                    ),
                                }
                        else:
                            payload = {"rows": op.save_rows}

                        apply_evaluation_payload(
                            db,
                            judge=judge,
                            item=item,
                            exercise=exercise,
                            payload=payload,
                        )
                        _record_client_op(
                            db,
                            user_id=int(judge.id),
                            client_op_id=op.client_op_id or op.id,
                            op_type="recovery_save_evaluation_list",
                            path=op.path
                            or f"/recovery/evaluation-lists/{item_id}/results",
                            response_body={
                                "ok": True,
                                "recovered": True,
                                "eval_item_id": int(item.id),
                                "source_eval_item_id": item_id,
                            },
                            exercise_id=int(exercise.id),
                        )
                        results_applied = True

            media_stats = _restore_media_for_item(
                db,
                judge=judge,
                exercise=exercise,
                item=item,
                media_rows=media_by_item.get(item_id, []),
            )
            restored_media += int(media_stats["media_restored"])
            missing_media += int(media_stats["media_missing"])
            images_restored += int(media_stats["images_restored"])
            videos_restored += int(media_stats["videos_restored"])

            if results_applied:
                restored_eval += 1
                if remapped_orphan:
                    status_label = f"تمت الاستعادة → القائمة #{int(item.id)}"
                else:
                    status_label = "تمت الاستعادة"
            elif int(media_stats["media_restored"]) > 0:
                status_label = "وسائط مستعادة (النتائج موجودة مسبقاً)"
            else:
                skipped += 1
                status_label = row.get("status") or "موجود مسبقاً"

            results.append(
                {
                    "eval_item_id": item_id,
                    "target_eval_item_id": int(item.id),
                    "ok": True,
                    "status": status_label,
                    "skipped": not results_applied
                    and int(media_stats["media_restored"]) == 0,
                    "media_restored": media_stats["media_restored"],
                    "media_missing": media_stats["media_missing"],
                    "media_errors": media_stats.get("media_errors") or [],
                    "open_url": (
                        f"/admin/evaluation-lists/{(item.unit_level_key or '').strip()}/view/{int(item.id)}"
                        if (item.unit_level_key or "").strip()
                        else row.get("open_url")
                    ),
                }
            )

        db.commit()
    except Exception:
        db.rollback()
        raise

    return {
        "selected": len(selected),
        "restored": restored_eval,
        "skipped": skipped,
        "conflicts": conflicts,
        "media_restored": restored_media,
        "images_restored": images_restored,
        "videos_restored": videos_restored,
        "missing_media": missing_media,
        "items": results,
    }
