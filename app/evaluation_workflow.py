"""مسار اعتماد قوائم التقييم: محكم → كبير محكمين → سيطرة."""
from __future__ import annotations

from datetime import datetime

from app.evaluation_list_columns import display_grade_label
from app.models import (
    EvaluationListPdfItem,
    EvaluationListSavedResult,
    PlannerFlowBundleEvalSavedResult,
)

SavedRow = EvaluationListSavedResult | PlannerFlowBundleEvalSavedResult


def eval_judge_approved(saved: SavedRow | None) -> bool:
    return bool(saved and getattr(saved, "is_approved", False))


def eval_reopened_for_judge(saved: SavedRow | None) -> bool:
    return bool(saved and getattr(saved, "reopened_for_judge", False))


def eval_chief_approved(saved: SavedRow | None) -> bool:
    return bool(saved and getattr(saved, "is_chief_approved", False))


def eval_control_approved(saved: SavedRow | None) -> bool:
    return bool(saved and getattr(saved, "is_control_approved", False))


def eval_status_done(saved: SavedRow | None) -> bool:
    """موقف ينجز/لم ينجز — يعتمد على اعتماد المحكم؛ يبقى ينجز بعد إعادة الفتح حتى يحفظ المحكم."""
    if saved is None:
        return False
    if eval_reopened_for_judge(saved) and eval_judge_approved(saved):
        return True
    return eval_judge_approved(saved)


def eval_judge_can_edit(saved: SavedRow | None) -> bool:
    if saved is None:
        return True
    if eval_reopened_for_judge(saved):
        return True
    return not eval_judge_approved(saved)


def eval_judge_can_approve(saved: SavedRow | None) -> bool:
    if saved is None or not (getattr(saved, "payload_json", None) or "").strip():
        return False
    return eval_judge_can_edit(saved)


def eval_chief_can_approve(saved: SavedRow | None) -> bool:
    return (
        eval_judge_approved(saved)
        and not eval_reopened_for_judge(saved)
        and not eval_chief_approved(saved)
    )


def eval_chief_can_reopen(saved: SavedRow | None) -> bool:
    return eval_judge_approved(saved) and not eval_control_approved(saved)


def apply_judge_approve(saved: SavedRow, user_id: int | None) -> None:
    saved.is_approved = True
    saved.approved_by_id = user_id
    saved.approved_at = datetime.utcnow()
    saved.reopened_for_judge = False
    saved.is_chief_approved = False
    saved.chief_approved_by_id = None
    saved.chief_approved_at = None


def apply_chief_approve(saved: SavedRow, user_id: int | None) -> None:
    if not eval_judge_approved(saved):
        raise ValueError("judge approval required")
    saved.is_chief_approved = True
    saved.chief_approved_by_id = user_id
    saved.chief_approved_at = datetime.utcnow()
    saved.reopened_for_judge = False


def apply_chief_reopen(saved: SavedRow) -> None:
    if not eval_judge_approved(saved):
        raise ValueError("judge approval required")
    saved.reopened_for_judge = True
    saved.is_chief_approved = False
    saved.chief_approved_by_id = None
    saved.chief_approved_at = None


def apply_judge_save_after_reopen(saved: SavedRow) -> None:
    """بعد حفظ المحكم لتعديلاته عقب إعادة الفتح: إلغاء اعتماده ليظهر لم ينجز وبانتظار الإعتماد."""
    if not eval_reopened_for_judge(saved):
        return
    saved.is_approved = False
    saved.approved_by_id = None
    saved.approved_at = None
    saved.reopened_for_judge = False


def eval_dispatch_status_ar(saved: SavedRow | None) -> tuple[str, str]:
    """
    عمود «إرسال للاعتماد» في جدول قوائم التقييم.
    يُرجع (التسمية، صنف لون الصف: none | pending | sent | returned).
    """
    has_payload = bool(saved and (getattr(saved, "payload_json", None) or "").strip())
    if not has_payload:
        return ("لم يُرسل", "none")
    if eval_reopened_for_judge(saved):
        return ("معاد للتعديل", "returned")
    if eval_judge_approved(saved):
        return ("مرسل", "sent")
    return ("بانتظار الإعتماد", "pending")


def evaluation_unit_home_rows(
    db,
    exercise,
    unit_levels: list[dict],
) -> list[dict]:
    """صفوف صفحة مستويات الوحدات: عدد القوائم المخصصة وغير المنجزة لكل وحدة."""
    if exercise is None:
        return [
            {
                "key": (u.get("key") or "").strip(),
                "label": (u.get("label") or u.get("key") or "").strip(),
                "total_count": 0,
                "not_done_count": 0,
            }
            for u in unit_levels
        ]
    ex_id = int(exercise.id)
    items = (
        db.query(EvaluationListPdfItem)
        .filter(EvaluationListPdfItem.exercise_id == ex_id)
        .all()
    )
    item_ids = [int(it.id) for it in items]
    canonical: dict[int, EvaluationListSavedResult] = {}
    if item_ids:
        saved_rows = (
            db.query(EvaluationListSavedResult)
            .filter(
                EvaluationListSavedResult.exercise_id == ex_id,
                EvaluationListSavedResult.evaluation_item_id.in_(item_ids),
            )
            .order_by(
                EvaluationListSavedResult.updated_at.desc(),
                EvaluationListSavedResult.id.desc(),
            )
            .all()
        )
        for row in saved_rows:
            iid = int(row.evaluation_item_id)
            if iid not in canonical:
                canonical[iid] = row
    by_unit: dict[str, dict[str, int]] = {}
    for it in items:
        uk = (it.unit_level_key or "").strip()
        if not uk:
            continue
        slot = by_unit.setdefault(uk, {"total": 0, "not_done": 0})
        slot["total"] += 1
        if not eval_judge_approved(canonical.get(int(it.id))):
            slot["not_done"] += 1
    rows: list[dict] = []
    for u in unit_levels:
        uk = (u.get("key") or "").strip()
        st = by_unit.get(uk, {"total": 0, "not_done": 0})
        rows.append(
            {
                "key": uk,
                "label": (u.get("label") or uk).strip(),
                "total_count": int(st["total"]),
                "not_done_count": int(st["not_done"]),
            }
        )
    return rows


def evaluation_unit_home_totals(unit_rows: list[dict]) -> dict[str, int]:
    """إجماليات أعلى جدول مستويات الوحدات."""
    return {
        "total": sum(int(r.get("total_count") or 0) for r in unit_rows),
        "not_done": sum(int(r.get("not_done_count") or 0) for r in unit_rows),
    }


def build_planner_flow_eval_row(
    *,
    slot_index: int,
    item_title: str,
    saved: SavedRow | None,
    exercise,
    open_href: str,
    dt_fallback=None,
    **extra,
) -> dict:
    """صف جدول قوائم تقييم إجراءات حزمة المجرى."""
    is_done = eval_status_done(saved)
    dispatch_label, row_tone = eval_dispatch_status_ar(saved)
    return {
        "slot_index": int(slot_index),
        "item_title": (item_title or "قائمة التقييم").strip(),
        "dt": (getattr(saved, "updated_at", None) if saved else None) or dt_fallback,
        "exercise_type": (getattr(exercise, "exercise_type", "") or "").strip(),
        "trained_unit": (getattr(exercise, "trained_unit", "") or "").strip(),
        "delivery_dt": (
            getattr(saved, "approved_at", None)
            if saved is not None and eval_judge_approved(saved)
            else None
        ),
        "status_label": "ينجز" if is_done else "لم ينجز",
        "status_done": is_done,
        "grade_label": display_grade_label(getattr(saved, "grade_label", "") if saved else "") if saved else "",
        "dispatch_label": dispatch_label,
        "row_tone": row_tone,
        "workflow_label": eval_workflow_label_ar(saved),
        "open_href": open_href,
        **extra,
    }


def build_evaluation_list_row(
    *,
    item,
    saved: SavedRow | None,
    exercise,
    open_href: str,
    **extra,
) -> dict:
    """صف جدول قوائم التقييم (محكم / مخطط / كبير محكمين)."""
    is_done = eval_status_done(saved)
    dispatch_label, row_tone = eval_dispatch_status_ar(saved)
    return {
        "item_id": int(item.id),
        "item_title": (getattr(item, "text", None) or "تقييم").strip(),
        "dt": (getattr(saved, "updated_at", None) if saved else None)
        or getattr(item, "created_at", None),
        "exercise_type": (getattr(exercise, "exercise_type", "") or "").strip(),
        "trained_unit": (getattr(exercise, "trained_unit", "") or "").strip(),
        "delivery_dt": (
            getattr(saved, "approved_at", None)
            if saved is not None and eval_judge_approved(saved)
            else None
        ),
        "status_label": "ينجز" if is_done else "لم ينجز",
        "status_done": is_done,
        "grade_label": display_grade_label(getattr(saved, "grade_label", "") if saved else "") if saved else "",
        "dispatch_label": dispatch_label,
        "row_tone": row_tone,
        "open_href": open_href,
        **extra,
    }


def eval_workflow_label_ar(saved: SavedRow | None) -> str:
    if saved is None or not (getattr(saved, "payload_json", None) or "").strip():
        return "—"
    if not eval_judge_approved(saved):
        return "بانتظار اعتماد المحكم"
    if eval_reopened_for_judge(saved):
        return "معاد للمحكم"
    if not eval_chief_approved(saved):
        return "بانتظار اعتماد كبير المحكمين"
    if not eval_control_approved(saved):
        return "بانتظار اعتماد السيطرة"
    return "معتمد نهائياً"
