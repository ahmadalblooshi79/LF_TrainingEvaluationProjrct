"""مزامنة جدول مجرى الأحداث بين بنك المعلومات والتخطيط وصفحات المحكمين."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Callable

from sqlalchemy.orm import Session

from app.models import (
    ExercisePlannerFlowBundle,
    InformationBankEventFlowTable,
    JudgeTraineeAssignment,
)


def ibank_flow_table_document(
    db: Session,
    *,
    get_or_create_ibank_row: Callable,
    normalize_document: Callable,
) -> dict | None:
    row = get_or_create_ibank_row(db)
    raw = (getattr(row, "flow_table_json", None) or "").strip()
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return normalize_document(payload)


def match_ibank_day_for_planner(
    ibank_days: list[dict],
    planner_days: list[dict],
    day_id: str,
) -> dict | None:
    """مطابقة يوم بنك المعلومات مع اليوم المفتوح في التخطيط (المعرّف ثم التسمية ثم الترتيب)."""
    target_id = (day_id or "").strip()
    if not target_id or not ibank_days:
        return None
    for d in ibank_days:
        if str(d.get("id") or "") == target_id:
            return d
    target = next(
        (d for d in planner_days if str(d.get("id") or "") == target_id),
        None,
    )
    if target is None:
        return None
    tlabel = str(target.get("label") or "").strip()
    if tlabel:
        labeled = [
            d for d in ibank_days if str(d.get("label") or "").strip() == tlabel
        ]
        if labeled:
            return labeled[0]
    idx = next(
        (i for i, d in enumerate(planner_days) if str(d.get("id") or "") == target_id),
        -1,
    )
    if 0 <= idx < len(ibank_days):
        return ibank_days[idx]
    return None


def merge_ibank_day_into_planner_days(
    planner_days: list[dict],
    ibank_days: list[dict],
    *,
    day_id: str,
) -> tuple[list[dict] | None, dict | None, str | None]:
    """يستبدل يوم التخطيط المطابق فقط. يعيد (الأيام المدمجة، اليوم المسحوب، رمز الخطأ)."""
    src = match_ibank_day_for_planner(ibank_days, planner_days, day_id)
    if src is None:
        return None, None, "day_missing"
    want = (day_id or "").strip()
    merged: list[dict] = []
    pulled: dict | None = None
    for d in planner_days:
        if str(d.get("id") or "") != want:
            merged.append(d)
            continue
        updated = dict(d)
        updated["label"] = str(src.get("label") or d.get("label") or "")
        updated["note"] = str(src.get("note") or "")
        updated["phase_key"] = str(src.get("phase_key") or "")
        updated["rows"] = list(src.get("rows") or [])
        merged.append(updated)
        pulled = updated
    if pulled is None:
        return None, None, "day_missing"
    return merged, pulled, None


def _flow_document_has_content(doc: dict | None) -> bool:
    if not doc or not isinstance(doc, dict):
        return False
    days = doc.get("days")
    if not isinstance(days, list):
        return False
    return any(
        isinstance(d, dict)
        and (
            (d.get("rows") and len(d.get("rows") or []) > 0)
            or (str(d.get("note") or "").strip())
        )
        for d in days
    )


def distribute_flow_document_to_judge_bundles(
    db: Session,
    *,
    exercise_id: int,
    doc: dict,
    source_bundle: ExercisePlannerFlowBundle | None,
    get_or_create_bundle: Callable,
    label_for_unit_key: Callable[[str], str],
    normalize_phase: Callable[[str | None], str],
    default_phase_key: Callable[[], str],
    resolve_unit_key_for_assignment: Callable[[JudgeTraineeAssignment], str] | None = None,
) -> dict[str, int]:
    """نسخ الجدول إلى حزم محكمي التمرين وربط الإسنادات."""
    payload = json.dumps(doc, ensure_ascii=False)
    phase_key = normalize_phase(
        (getattr(source_bundle, "exercise_phase", None) or "").strip()
        or default_phase_key()
    )
    now = datetime.utcnow()
    updated_ids: set[int] = set()
    distributed_count = 0

    if source_bundle is not None:
        source_bundle.flow_table_json = payload
        source_bundle.updated_at = now
        updated_ids.add(int(source_bundle.id))

    assignments = (
        db.query(JudgeTraineeAssignment)
        .filter(JudgeTraineeAssignment.exercise_id == int(exercise_id))
        .all()
    )
    for ja in assignments:
        uk = (ja.unit_level_key or "").strip()
        if not uk and resolve_unit_key_for_assignment is not None:
            uk = (resolve_unit_key_for_assignment(ja) or "").strip()
        if not uk:
            if source_bundle is not None:
                ja.planner_flow_bundle_id = int(source_bundle.id)
                distributed_count += 1
            continue
        unit_label = (label_for_unit_key(uk) or uk)[:200]
        bundle = get_or_create_bundle(
            db,
            int(exercise_id),
            phase_key,
            uk,
            unit_label,
        )
        bundle.flow_table_json = payload
        bundle.updated_at = now
        ja.planner_flow_bundle_id = int(bundle.id)
        updated_ids.add(int(bundle.id))
        distributed_count += 1

    return {
        "bundle_count": len(updated_ids),
        "judge_assignment_count": len(assignments),
        "distributed_assignment_count": distributed_count,
    }


def ibank_row_has_flow_content(db: Session) -> bool:
    row = (
        db.query(InformationBankEventFlowTable)
        .order_by(InformationBankEventFlowTable.id)
        .first()
    )
    if row is None:
        return False
    raw = (row.flow_table_json or "").strip()
    if not raw:
        return False
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return False
    if isinstance(data, dict) and isinstance(data.get("days"), list):
        return _flow_document_has_content({"days": data["days"]})
    if isinstance(data, list):
        return len(data) > 0
    return bool(data)


def bundle_has_flow_table(bundle: ExercisePlannerFlowBundle | None) -> bool:
    if bundle is None:
        return False
    raw = (getattr(bundle, "flow_table_json", None) or "").strip()
    if not raw:
        return False
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return False
    if isinstance(data, dict):
        return _flow_document_has_content(data)
    return bool(data)
