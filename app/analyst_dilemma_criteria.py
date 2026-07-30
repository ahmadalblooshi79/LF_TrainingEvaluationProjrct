"""تبويب قوائم تقييم المعاضل ضمن معايير التقييم — مستقل عن تبويب المراحل."""

from __future__ import annotations

from flask import request
from sqlalchemy.orm import Session

from app.analyst_flow_day_phase_link import (
    build_dilemma_reaction_table_for_unit_phase,
    collect_flow_acquired_by_unit_phase,
    day_phase_link_rows_for_ui,
    load_analyst_day_phase_map,
    save_analyst_day_phase_links,
)
from app.info_bank_tree import ibank_event_flow_days
from app.models.domain import (
    AnalystDilemmaCriteriaPhaseItem,
    AnalystDilemmaCriteriaUnit,
    Exercise,
)
from app.unit_levels_catalog import UNIT_LEVELS, label_for_unit_level_key


def sync_dilemma_criteria_units_from_planner(db: Session, ex: Exercise) -> list[AnalystDilemmaCriteriaUnit]:
    from app.views import (
        _planner_unit_keys_for_exercise,
        _resolve_unit_level_key_for_criteria_label,
    )

    planner_keys = _planner_unit_keys_for_exercise(db, ex)
    existing = (
        db.query(AnalystDilemmaCriteriaUnit)
        .filter(AnalystDilemmaCriteriaUnit.exercise_id == ex.id)
        .order_by(AnalystDilemmaCriteriaUnit.sort_order, AnalystDilemmaCriteriaUnit.id)
        .all()
    )
    by_key: dict[str, AnalystDilemmaCriteriaUnit] = {}
    for row in existing:
        uk = _resolve_unit_level_key_for_criteria_label(row.label or "")
        if uk:
            by_key[uk] = row

    max_sort = max((int(r.sort_order or 0) for r in existing), default=-1)
    dirty = False
    for key in planner_keys:
        catalog_label = (label_for_unit_level_key(key, db=db) or key)[:300]
        row = by_key.get(key)
        if row is None:
            max_sort += 1
            db.add(
                AnalystDilemmaCriteriaUnit(
                    exercise_id=ex.id,
                    sort_order=max_sort,
                    label=catalog_label,
                )
            )
            dirty = True
        elif catalog_label and row.label != catalog_label:
            row.label = catalog_label
            dirty = True

    if dirty:
        db.commit()

    return (
        db.query(AnalystDilemmaCriteriaUnit)
        .filter(AnalystDilemmaCriteriaUnit.exercise_id == ex.id)
        .order_by(AnalystDilemmaCriteriaUnit.sort_order, AnalystDilemmaCriteriaUnit.id)
        .all()
    )


def build_dilemma_criteria_distribution(db: Session, user) -> dict:
    """توزيع النسبة المئوية لقوائم تقييم المعاضل — نتائج حسب الأيام المرتبطة بالمراحل."""
    from app.views import (
        EXERCISE_PHASE_OPTIONS,
        _analyst_criteria_phases_for_display,
        _current_workspace_exercise,
        _resolve_unit_level_key_for_criteria_label,
    )
    from app.planning_catalog_sync import sync_planning_catalogs_from_db

    sync_planning_catalogs_from_db(db, force=True)
    ex0 = _current_workspace_exercise(db, user)
    if ex0 is None:
        return {"has_exercise": False}
    ex = db.query(Exercise).filter(Exercise.id == ex0.id).first()
    if ex is None:
        return {"has_exercise": False}

    criteria_units = sync_dilemma_criteria_units_from_planner(db, ex)
    phases = _analyst_criteria_phases_for_display(True) or list(EXERCISE_PHASE_OPTIONS)
    flow_days = ibank_event_flow_days(db)
    day_to_phase = load_analyst_day_phase_map(db, int(ex.id))
    flow_acquired = collect_flow_acquired_by_unit_phase(
        db,
        exercise_id=int(ex.id),
        day_to_phase=day_to_phase,
        flow_days=flow_days,
    )

    # علامات يدوية محفوظة في تفاصيل المرحلة (إن وُجدت تُفضَّل على نتيجة المجرى)
    phase_items = (
        db.query(AnalystDilemmaCriteriaPhaseItem)
        .filter(AnalystDilemmaCriteriaPhaseItem.exercise_id == ex.id)
        .all()
    )
    marks_by_unit_phase: dict[tuple[int, str], list[float]] = {}
    for item in phase_items:
        if item.allocated_mark is None:
            continue
        marks_by_unit_phase.setdefault(
            (int(item.criteria_unit_id), item.phase_key or ""),
            [],
        ).append(float(item.allocated_mark))

    rows: list[dict] = []
    grand_total = 0.0
    for unit in criteria_units:
        phase_totals: dict[str, float | None] = {}
        unit_level_key = _resolve_unit_level_key_for_criteria_label(unit.label or "")
        for phase_key, _label in phases:
            marks = marks_by_unit_phase.get((unit.id, phase_key), [])
            if marks:
                phase_totals[phase_key] = sum(marks)
            else:
                flow_v = flow_acquired.get((unit_level_key, phase_key))
                phase_totals[phase_key] = (
                    float(flow_v) if flow_v is not None and flow_v > 0 else None
                )
        parts = [x for x in phase_totals.values() if x is not None]
        total_mark = sum(parts) if parts else None
        if total_mark is not None:
            grand_total += total_mark
        unit_label = label_for_unit_level_key(unit_level_key) or (unit.label or "—")
        rows.append(
            {
                "unit_id": unit.id,
                "unit_level_key": unit_level_key,
                "unit_label": unit_label,
                "phase_totals": phase_totals,
                "total_mark": total_mark,
                "allocated_pct": None,
            }
        )

    if grand_total > 0:
        for row in rows:
            if row["total_mark"] is not None:
                row["allocated_pct"] = (float(row["total_mark"]) / grand_total) * 100.0

    present_keys = {(r.get("unit_level_key") or "").strip() for r in rows}
    available_unit_levels = [
        u for u in UNIT_LEVELS if (u.get("key") or "").strip() not in present_keys
    ]

    return {
        "has_exercise": True,
        "exercise": ex,
        "distribution_rows": rows,
        "grand_total": grand_total if grand_total > 0 else None,
        "criteria_phases": phases,
        "available_unit_levels": available_unit_levels,
        "day_phase_links": day_phase_link_rows_for_ui(
            db, int(ex.id), phase_options=list(phases), flow_days=flow_days
        ),
        "flow_days": flow_days,
    }


def save_dilemma_criteria_distribution(db: Session, user, ex: Exercise) -> None:
    del user
    from app.views import _resolve_unit_level_key_for_criteria_label

    existing = {
        int(row.id): row
        for row in (
            db.query(AnalystDilemmaCriteriaUnit)
            .filter(AnalystDilemmaCriteriaUnit.exercise_id == ex.id)
            .all()
        )
    }
    delete_ids = {
        int(x)
        for x in request.form.getlist("delete_unit_ids")
        if (x or "").strip().isdigit()
    }
    ordered_ids = [
        int(x)
        for x in request.form.getlist("unit_ids")
        if (x or "").strip().isdigit()
    ]
    for sort_order, uid in enumerate(ordered_ids):
        row = existing.get(uid)
        if row is None:
            continue
        if uid in delete_ids:
            db.query(AnalystDilemmaCriteriaPhaseItem).filter(
                AnalystDilemmaCriteriaPhaseItem.criteria_unit_id == uid
            ).delete(synchronize_session=False)
            db.delete(row)
            continue
        unit_key = (request.form.get(f"unit_level_key__{uid}") or "").strip()
        if unit_key:
            catalog_label = label_for_unit_level_key(unit_key)
            if catalog_label:
                row.label = catalog_label[:300]
        row.sort_order = sort_order
    new_key = (request.form.get("new_unit_level_key") or "").strip()
    if new_key:
        catalog_label = label_for_unit_level_key(new_key) or new_key
        exists = (
            db.query(AnalystDilemmaCriteriaUnit)
            .filter(AnalystDilemmaCriteriaUnit.exercise_id == ex.id)
            .all()
        )
        if not any(
            _resolve_unit_level_key_for_criteria_label(r.label or "") == new_key
            for r in exists
        ):
            db.add(
                AnalystDilemmaCriteriaUnit(
                    exercise_id=ex.id,
                    sort_order=len(ordered_ids),
                    label=catalog_label[:300],
                )
            )
    db.commit()


def save_day_phase_links_from_request(db: Session, ex: Exercise) -> None:
    day_ids = list(request.form.getlist("flow_day_id"))
    phase_keys = list(request.form.getlist("link_phase_key"))
    delete_ids = {
        (x or "").strip()
        for x in request.form.getlist("delete_day_ids")
        if (x or "").strip()
    }
    save_analyst_day_phase_links(
        db,
        int(ex.id),
        day_ids=day_ids,
        phase_keys=phase_keys,
        delete_day_ids=delete_ids,
    )


def dilemma_criteria_phase_items_for_unit(
    db: Session,
    ex: Exercise,
    unit: AnalystDilemmaCriteriaUnit,
    phase_key: str,
) -> tuple[list[dict], list[str]]:
    """عناصر تفاصيل المرحلة + تسميات الأيام المشمولة."""
    from app.views import (
        _analyst_criteria_phase_db_keys,
        _resolve_unit_level_key_for_criteria_label,
    )

    unit_level_key = _resolve_unit_level_key_for_criteria_label(unit.label or "")
    day_to_phase = load_analyst_day_phase_map(db, int(ex.id))
    flow_days = ibank_event_flow_days(db)
    reaction = build_dilemma_reaction_table_for_unit_phase(
        db,
        exercise_id=int(ex.id),
        unit_level_key=unit_level_key,
        phase_key=phase_key,
        day_to_phase=day_to_phase,
        flow_days=flow_days,
    )
    day_labels = list(reaction.get("day_labels") or [])

    phase_db_keys = _analyst_criteria_phase_db_keys(phase_key)
    saved_rows = (
        db.query(AnalystDilemmaCriteriaPhaseItem)
        .filter(
            AnalystDilemmaCriteriaPhaseItem.exercise_id == ex.id,
            AnalystDilemmaCriteriaPhaseItem.criteria_unit_id == unit.id,
            AnalystDilemmaCriteriaPhaseItem.phase_key.in_(phase_db_keys),
        )
        .order_by(
            AnalystDilemmaCriteriaPhaseItem.sort_order,
            AnalystDilemmaCriteriaPhaseItem.id,
        )
        .all()
    )
    marks_by_text: dict[str, float | None] = {}
    marks_by_index: list[float | None] = []
    for row in saved_rows:
        text = (row.criteria_text or "").strip()
        mark = float(row.allocated_mark) if row.allocated_mark is not None else None
        marks_by_index.append(mark)
        if text and text not in marks_by_text:
            marks_by_text[text] = mark

    list_titles: list[str] = []
    seen: set[str] = set()
    reaction_acq: dict[str, float | None] = {}
    for r in reaction.get("rows") or []:
        title = (r.get("list_title") or "").strip()
        if not title or title == "—" or title in seen:
            continue
        seen.add(title)
        list_titles.append(title[:1000])
        acq = r.get("acquired")
        reaction_acq[title] = float(acq) if isinstance(acq, (int, float)) else None

    if not list_titles and saved_rows:
        for row in saved_rows:
            title = (row.criteria_text or "").strip()
            if title and title not in seen:
                seen.add(title)
                list_titles.append(title[:1000])

    merged: list[dict] = []
    for idx, title in enumerate(list_titles):
        mark = marks_by_text.get(title)
        if mark is None and idx < len(marks_by_index):
            mark = marks_by_index[idx]
        if mark is None:
            mark = reaction_acq.get(title)
        merged.append(
            {
                "criteria_text": title,
                "allocated_mark": mark,
                "from_evaluation_list": True,
            }
        )

    total_mark = sum(
        float(m or 0) for m in (r["allocated_mark"] for r in merged) if m is not None
    )
    for row in merged:
        mark = row.get("allocated_mark")
        row["allocated_pct"] = (
            (float(mark) / total_mark * 100.0)
            if mark is not None and total_mark > 0
            else None
        )
    return merged, day_labels


def save_dilemma_criteria_phase_items(
    db: Session,
    ex: Exercise,
    unit: AnalystDilemmaCriteriaUnit,
    phase_key: str,
) -> None:
    from app.views import (
        _analyst_criteria_phase_db_keys,
        _parse_mark_form_value,
        _resolve_analyst_criteria_phase_key,
    )

    phase_db_keys = _analyst_criteria_phase_db_keys(phase_key)
    db.query(AnalystDilemmaCriteriaPhaseItem).filter(
        AnalystDilemmaCriteriaPhaseItem.exercise_id == ex.id,
        AnalystDilemmaCriteriaPhaseItem.criteria_unit_id == unit.id,
        AnalystDilemmaCriteriaPhaseItem.phase_key.in_(phase_db_keys),
    ).delete(synchronize_session=False)
    storage_key = _resolve_analyst_criteria_phase_key(phase_key) or phase_key
    criteria_texts = [
        (t or "").strip()[:1000] for t in request.form.getlist("criteria_text")
    ]
    marks = request.form.getlist("allocated_mark")
    n = max(len(criteria_texts), len(marks))
    for idx in range(n):
        text_value = (criteria_texts[idx] if idx < len(criteria_texts) else "").strip()[
            :1000
        ]
        mark = _parse_mark_form_value(marks[idx] if idx < len(marks) else "")
        if not text_value and mark is None:
            continue
        db.add(
            AnalystDilemmaCriteriaPhaseItem(
                exercise_id=ex.id,
                criteria_unit_id=unit.id,
                phase_key=storage_key,
                sort_order=idx,
                criteria_text=text_value,
                allocated_mark=mark,
            )
        )
    db.commit()
