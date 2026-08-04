# -*- coding: utf-8 -*-
"""وحدات تجميعية لقوائم تقييم المعاضل في التقرير النهائي (حسب مرحلة الأيام)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.analyst_dilemma_criteria import unit_keys_for_action_eval_flow_day
from app.analyst_flow_day_phase_link import (
    _normalize_phase_key,
    build_dilemma_reaction_table_for_unit_phase,
    ensure_default_analyst_day_phase_links,
)
from app.models.domain import (
    AnalystDilemmaCriteriaPhaseItem,
    AnalystDilemmaCriteriaUnit,
    Exercise,
)

# (unit_key, unit_label, phase_key)
DILEMMA_REACTION_FINAL_UNITS: tuple[tuple[str, str, str], ...] = (
    (
        "fe_dilemma_reaction_opening",
        "رد الفعل على معاضل التنقل التعبوي",
        "opening",
    ),
    (
        "fe_dilemma_reaction_offensive",
        "رد الفعل على معاضل العمليات التعرضية",
        "battle_exposure",
    ),
)

DILEMMA_REACTION_UNIT_SORT: dict[str, int] = {
    "fe_dilemma_reaction_opening": 90001,
    "fe_dilemma_reaction_offensive": 90002,
}

DILEMMA_REACTION_PHASE_BY_UNIT: dict[str, str] = {
    uk: pk for uk, _lbl, pk in DILEMMA_REACTION_FINAL_UNITS
}


def is_dilemma_reaction_unit_key(unit_key: str) -> bool:
    return (unit_key or "").strip() in DILEMMA_REACTION_PHASE_BY_UNIT


def _dilemma_phase_match_keys(phase_key: str) -> set[str]:
    from app.exercise_phase_catalog import normalize_exercise_phase
    from app.views import _analyst_criteria_phase_db_keys

    pk = (phase_key or "").strip()
    keys: set[str] = set()
    if pk:
        keys.add(pk)
    for k in _analyst_criteria_phase_db_keys(pk):
        if k:
            keys.add(k)
    norm = normalize_exercise_phase(pk)
    if norm:
        keys.add(norm)
    if "battle_exposure" in keys or pk == "battle_exposure":
        keys.update({"battle_exposure", "main"})
    if "main" in keys or pk == "main":
        keys.update({"battle_exposure", "main"})
    if "opening" in keys or pk == "opening":
        keys.add("opening")
    return {k for k in keys if k}


def dilemma_criteria_allocated_max_for_phase(
    db: Session,
    exercise_id: int,
    phase_key: str,
    *,
    unit_keys: set[str] | None = None,
) -> float:
    """قصوى التوزيع = مجموع علامات معايير المعاضل للمرحلة (عمود التوزيع/التفاصيل)."""
    from app.views import _resolve_unit_level_key_for_criteria_label

    phase_keys = _dilemma_phase_match_keys(phase_key)
    if not phase_keys:
        return 0.0
    criteria_units = (
        db.query(AnalystDilemmaCriteriaUnit)
        .filter(AnalystDilemmaCriteriaUnit.exercise_id == int(exercise_id))
        .all()
    )
    unit_id_to_key: dict[int, str] = {}
    for cu in criteria_units:
        uk = _resolve_unit_level_key_for_criteria_label(cu.label or "")
        if uk:
            unit_id_to_key[int(cu.id)] = uk
    if not unit_id_to_key:
        return 0.0
    want_units = {(u or "").strip() for u in (unit_keys or set()) if (u or "").strip()}
    items = (
        db.query(AnalystDilemmaCriteriaPhaseItem)
        .filter(AnalystDilemmaCriteriaPhaseItem.exercise_id == int(exercise_id))
        .all()
    )
    total = 0.0
    for item in items:
        if item.allocated_mark is None:
            continue
        pk = (item.phase_key or "").strip()
        if pk not in phase_keys and not (_dilemma_phase_match_keys(pk) & phase_keys):
            continue
        uk = unit_id_to_key.get(int(item.criteria_unit_id or 0), "")
        if want_units and uk not in want_units:
            continue
        total += float(item.allocated_mark)
    return total


def _unit_keys_and_days_for_phase(
    db: Session,
    exercise_id: int,
    phase_key: str,
    *,
    day_to_phase: dict[str, str],
    flow_days: list[dict],
) -> tuple[set[str], list[str], set[str]]:
    from app.exercise_phase_catalog import normalize_exercise_phase

    pk = normalize_exercise_phase(phase_key) or phase_key
    match_keys = _dilemma_phase_match_keys(pk)
    days_by_phase: dict[str, list[str]] = {}
    for day in flow_days or []:
        did = str(day.get("id") or "").strip()
        if not did:
            continue
        dpk = _normalize_phase_key(day_to_phase.get(did) or "")
        if not dpk:
            continue
        days_by_phase.setdefault(dpk, []).append(did)
        if dpk == "main":
            days_by_phase.setdefault("battle_exposure", []).append(did)
        if dpk == "battle_exposure":
            days_by_phase.setdefault("main", []).append(did)

    day_ids: list[str] = []
    seen_d: set[str] = set()
    for mk in match_keys:
        for did in days_by_phase.get(mk) or []:
            if did not in seen_d:
                seen_d.add(did)
                day_ids.append(did)

    unit_keys: set[str] = set()
    for did in day_ids:
        for uk in unit_keys_for_action_eval_flow_day(
            db,
            int(exercise_id),
            phase_key=pk,
            flow_day_id=did,
        ):
            if uk:
                unit_keys.add(uk)
    return unit_keys, day_ids, match_keys


def _reaction_list_totals_for_units(
    db: Session,
    exercise_id: int,
    phase_key: str,
    unit_keys: set[str],
    *,
    day_to_phase: dict[str, str],
    flow_days: list[dict],
) -> tuple[float, float, list[dict]]:
    """(مجموع مكتسبة القوائم, مجموع قصوى القوائم, صفوف التفاصيل) — للتحويل إلى مقياس التوزيع فقط."""
    from app.unit_levels_catalog import label_for_unit_level_key

    day_order: dict[str, int] = {}
    for idx, day in enumerate(flow_days or []):
        did = str(day.get("id") or "").strip()
        if did and did not in day_order:
            day_order[did] = idx

    detail_rows: list[dict] = []
    list_acq = 0.0
    list_max = 0.0
    for uk in sorted(unit_keys):
        reaction = build_dilemma_reaction_table_for_unit_phase(
            db,
            exercise_id=int(exercise_id),
            unit_level_key=uk,
            phase_key=phase_key,
            day_to_phase=day_to_phase,
            flow_days=flow_days,
        )
        acq = reaction.get("total_acquired")
        mx = reaction.get("total_max")
        if acq is not None:
            list_acq += float(acq)
        if mx is not None:
            list_max += float(mx)
        for r in reaction.get("rows") or []:
            detail_rows.append(
                {
                    **r,
                    "unit_key": uk,
                    "unit_label": label_for_unit_level_key(uk, db=db) or uk,
                }
            )

    # المعضلة/1 لليوم/1 ثم المعضلة/1 لليوم/2… ثم المعضلة/2 لليوم/1… وهكذا
    detail_rows.sort(
        key=lambda r: (
            int(r.get("dilemma_no") or 0),
            day_order.get(str(r.get("day_id") or "").strip(), 10_000),
            str(r.get("unit_label") or r.get("unit_key") or ""),
            str(r.get("list_title") or ""),
        )
    )
    for seq, row in enumerate(detail_rows, start=1):
        row["seq"] = seq
    return list_acq, list_max, detail_rows


def build_dilemma_reaction_final_eval_rows(
    db: Session,
    exercise_id: int,
) -> list[dict]:
    """صفوف وحدتين تجميعيّتين للتقرير النهائي.

    القصوى: مجموع علامات توزيع قوائم تقييم المعاضل (allocated_mark) للمرحلة —
            وليس مجموع قصوى حمولات قوائم الإجراءات.
    المكتسبة: نسبة أداء قوائم الإجراءات × القصوى أعلاه —
              وليس مجموع مكتسبة الحمولات مباشرةً (لتفادي وضع «المجموع العام» في العمودين).
    """
    from app.evaluation_list_columns import grade_label_from_percent
    from app.exercise_phase_catalog import normalize_exercise_phase
    from app.info_bank_tree import ibank_event_flow_days
    from app.views import _phase_label_ar

    flow_days = ibank_event_flow_days(db)
    day_to_phase = ensure_default_analyst_day_phase_links(
        db, int(exercise_id), flow_days=flow_days
    )

    rows: list[dict] = []
    for unit_key, unit_label, phase_key in DILEMMA_REACTION_FINAL_UNITS:
        pk = normalize_exercise_phase(phase_key) or phase_key
        unit_keys, _day_ids, _match = _unit_keys_and_days_for_phase(
            db,
            int(exercise_id),
            pk,
            day_to_phase=day_to_phase,
            flow_days=flow_days,
        )

        # القصوى = مجموع علامات التوزيع/التفاصيل لتلك المرحلة ووحداتها
        max_mark = dilemma_criteria_allocated_max_for_phase(
            db, int(exercise_id), pk, unit_keys=unit_keys or None
        )
        if max_mark <= 0 and not unit_keys:
            max_mark = dilemma_criteria_allocated_max_for_phase(
                db, int(exercise_id), pk, unit_keys=None
            )

        list_acq, list_max, detail_rows = _reaction_list_totals_for_units(
            db,
            int(exercise_id),
            pk,
            unit_keys,
            day_to_phase=day_to_phase,
            flow_days=flow_days,
        )

        list_pct: float | None = None
        if list_max > 0:
            list_pct = (float(list_acq) / float(list_max)) * 100.0

        acquired_mark = 0.0
        phase_pct: float | None = None
        if max_mark > 0 and list_pct is not None:
            # مكتسبة على مقياس التوزيع = (نسبة القوائم ÷ 100) × قصوى التوزيع
            acquired_mark = round((float(list_pct) / 100.0) * float(max_mark), 2)
            phase_pct = float(list_pct)
        elif max_mark > 0:
            acquired_mark = 0.0
            phase_pct = 0.0
        # بلا قصوى توزيع: لا نملأ العمودين بمجموع الحمولات — النسبة من أداء القوائم فقط إن وُجد
        elif list_pct is not None:
            phase_pct = float(list_pct)

        phase_grade = (
            grade_label_from_percent(phase_pct) if phase_pct is not None else "—"
        )
        report_pk = "battle_exposure" if pk == "main" else pk
        rows.append(
            {
                "unit_key": unit_key,
                "unit_label": unit_label,
                "phase_key": report_pk,
                "phase_label": _phase_label_ar(report_pk),
                "max_mark": float(max_mark),
                "acquired_mark": float(acquired_mark),
                "phase_pct": phase_pct,
                "phase_grade": phase_grade,
                "unit_total_pct": phase_pct,
                "unit_grade": phase_grade,
                "is_dilemma_reaction_aggregate": True,
                "has_phase_manual_max": False,
                "manual_max_mark": None,
                "dilemma_detail_rows": detail_rows,
                "dilemma_component_unit_keys": sorted(unit_keys),
                "dilemma_list_acquired_total": float(list_acq),
                "dilemma_list_max_total": float(list_max),
            }
        )
    return rows


def build_dilemma_reaction_report_unit(
    db: Session,
    exercise_id: int,
    unit_key: str,
) -> dict | None:
    """بيانات صفحة تفاصيل وحدة رد الفعل التجميعية."""
    from app.exercise_phase_catalog import normalize_exercise_phase
    from app.info_bank_tree import ibank_event_flow_days
    from app.views import _phase_label_ar

    want = (unit_key or "").strip()
    meta = next((t for t in DILEMMA_REACTION_FINAL_UNITS if t[0] == want), None)
    if meta is None:
        return None
    _uk, unit_label, phase_key = meta
    pk = normalize_exercise_phase(phase_key) or phase_key
    report_pk = "battle_exposure" if pk == "main" else pk

    agg_rows = build_dilemma_reaction_final_eval_rows(db, int(exercise_id))
    agg = next((r for r in agg_rows if r.get("unit_key") == want), None)
    if agg is None:
        return None

    phase_row = {
        "unit_key": want,
        "unit_label": unit_label,
        "phase_key": report_pk,
        "phase_label": _phase_label_ar(report_pk),
        "max_mark": agg.get("max_mark"),
        "acquired_mark": agg.get("acquired_mark"),
        "phase_pct": agg.get("phase_pct"),
        "phase_grade": agg.get("phase_grade"),
        "unit_total_pct": agg.get("unit_total_pct"),
        "unit_grade": agg.get("unit_grade"),
        "show_unit_total": True,
        "unit_rowspan": 1,
        "is_dilemma_reaction_aggregate": True,
    }
    return {
        "unit_key": want,
        "unit_label": unit_label,
        "anchor": f"final-dilemma-{want}",
        "is_dilemma_reaction_aggregate": True,
        "show_evaluation_tracks": False,
        "phase_rows": [phase_row],
        "dilemma_phase_key": report_pk,
        "dilemma_phase_label": _phase_label_ar(report_pk),
        "dilemma_detail_rows": list(agg.get("dilemma_detail_rows") or []),
        "max_mark": agg.get("max_mark"),
        "acquired_mark": agg.get("acquired_mark"),
        "phase_pct": agg.get("phase_pct"),
        "phase_grade": agg.get("phase_grade"),
    }
