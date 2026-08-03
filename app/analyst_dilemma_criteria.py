"""تبويب قوائم تقييم المعاضل ضمن معايير التقييم — مستقل عن تبويب المراحل."""

from __future__ import annotations

from flask import request
from sqlalchemy.orm import Session

from app.analyst_flow_day_phase_link import (
    build_dilemma_reaction_table_for_unit_phase,
    day_phase_link_rows_for_ui,
    load_analyst_day_phase_map,
    save_analyst_day_phase_links,
    set_analyst_day_phase_link,
)
from app.evaluation_workflow import filter_evaluation_items_by_phase
from app.info_bank_tree import ibank_event_flow_days
from app.models.domain import (
    AnalystDilemmaCriteriaPhaseItem,
    AnalystDilemmaCriteriaUnit,
    EvaluationListPdfItem,
    Exercise,
    ExercisePlannerFlowBundle,
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


def unit_keys_for_evaluation_list_phase(
    db: Session,
    exercise_id: int,
    phase_key: str,
    *,
    day_to_phase: dict[str, str] | None = None,
    flow_days: list[dict] | None = None,
) -> list[str]:
    """مستويات الوحدات المعنية بمرحلة معيّنة.

    المصادر بالترتيب:
    1) قوائم التقييم المنشورة للتمرين (المراحل)
    2) حزم مجرى التخطيط لنفس المرحلة
    3) وحدات المكلفين في معاضل أيام المجرى المرتبطة بالمرحلة
    4) إن بقي فارغاً: مستويات الوحدة المعتمدة في التخطيط للتمرين
    """
    from app.exercise_phase_catalog import normalize_exercise_phase
    from app.views import (
        _analyst_criteria_phase_db_keys,
        _planner_unit_keys_for_exercise,
        _unit_level_order_expr,
    )

    pk = (phase_key or "").strip()
    if not pk:
        return []

    phase_match: set[str] = {pk}
    for k in _analyst_criteria_phase_db_keys(pk):
        if k:
            phase_match.add(k)
    norm = normalize_exercise_phase(pk)
    if norm:
        phase_match.add(norm)
    # توافق مفاتيح كتالوج بنك المعلومات (battle_exposure / reorganization)
    from app.analyst_flow_day_phase_link import _normalize_phase_key as _flow_norm

    flow_pk = _flow_norm(pk)
    if flow_pk:
        phase_match.add(flow_pk)

    keys: list[str] = []
    seen: set[str] = set()

    def _add(uk: str) -> None:
        u = (uk or "").strip()
        if not u or u in seen:
            return
        seen.add(u)
        keys.append(u)

    def _phase_matches(raw: str | None) -> bool:
        r = (raw or "").strip()
        if not r:
            return False
        if r in phase_match:
            return True
        rn = normalize_exercise_phase(r)
        if rn and rn in phase_match:
            return True
        rf = _flow_norm(r)
        return bool(rf and rf in phase_match)

    items = (
        db.query(EvaluationListPdfItem)
        .filter(EvaluationListPdfItem.exercise_id == int(exercise_id))
        .order_by(
            _unit_level_order_expr(EvaluationListPdfItem.unit_level_key),
            EvaluationListPdfItem.sort_order,
            EvaluationListPdfItem.id,
        )
        .all()
    )
    for it in filter_evaluation_items_by_phase(items, pk):
        _add(getattr(it, "unit_level_key", "") or "")

    bundles = (
        db.query(ExercisePlannerFlowBundle)
        .filter(ExercisePlannerFlowBundle.exercise_id == int(exercise_id))
        .order_by(
            _unit_level_order_expr(ExercisePlannerFlowBundle.unit_level_key),
            ExercisePlannerFlowBundle.id,
        )
        .all()
    )
    for b in bundles:
        if _phase_matches(getattr(b, "exercise_phase", None)):
            _add(getattr(b, "unit_level_key", "") or "")

    try:
        from app.ibank_action_eval_dilemma_tree import build_action_eval_dilemma_judge_tree
        from app.info_bank_tree import ibank_event_flow_days

        days_src = flow_days if flow_days is not None else ibank_event_flow_days(db)
        mapping = day_to_phase
        if mapping is None:
            from app.analyst_flow_day_phase_link import (
                ibank_flow_day_phase_map,
                load_analyst_day_phase_map,
            )

            mapping = dict(ibank_flow_day_phase_map(days_src))
            mapping.update(load_analyst_day_phase_map(db, int(exercise_id)))

        day_ids_for_phase: set[str] = set()
        for d in days_src or []:
            did = str(d.get("id") or "").strip()
            if not did:
                continue
            linked = (mapping or {}).get(did) or d.get("phase_key") or ""
            if _phase_matches(str(linked)):
                day_ids_for_phase.add(did)

        if day_ids_for_phase:
            tree = build_action_eval_dilemma_judge_tree(
                db, exercise_id=int(exercise_id)
            )
            for did in day_ids_for_phase:
                for dilemma in tree.get(did) or []:
                    for judge in dilemma.get("judges") or []:
                        _add(str(judge.get("unit_key") or ""))
    except Exception:
        pass

    if not keys:
        ex = db.get(Exercise, int(exercise_id))
        if ex is not None:
            for uk in _planner_unit_keys_for_exercise(db, ex):
                _add(uk)

    order = {u["key"]: idx for idx, u in enumerate(UNIT_LEVELS)}
    return sorted(keys, key=lambda k: order.get(k, len(order)))


def _ensure_dilemma_unit_for_key(
    db: Session, ex: Exercise, unit_key: str, existing_by_key: dict[str, AnalystDilemmaCriteriaUnit]
) -> AnalystDilemmaCriteriaUnit | None:
    uk = (unit_key or "").strip()
    if not uk:
        return None
    row = existing_by_key.get(uk)
    if row is not None:
        return row
    catalog_label = (label_for_unit_level_key(uk, db=db) or uk)[:300]
    max_sort = max(
        (int(r.sort_order or 0) for r in existing_by_key.values()),
        default=-1,
    )
    row = AnalystDilemmaCriteriaUnit(
        exercise_id=ex.id,
        sort_order=max_sort + 1,
        label=catalog_label,
    )
    db.add(row)
    db.flush()
    existing_by_key[uk] = row
    return row


def build_dilemma_criteria_distribution(
    db: Session,
    user,
    *,
    active_day_id: str | None = None,
    active_phase_key: str | None = None,
    persist_day_phase: bool = False,
) -> dict:
    """توزيع النسبة المئوية لقوائم تقييم المعاضل — حسب يوم التبويب والمرحلة المختارة."""
    from app.views import (
        EXERCISE_PHASE_OPTIONS,
        _analyst_criteria_phases_for_display,
        _current_workspace_exercise,
        _resolve_analyst_criteria_phase_key,
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
    day_tabs = [
        {
            "day_id": str(d.get("id") or "").strip(),
            "day_label": str(d.get("label") or d.get("id") or "").strip(),
        }
        for d in (flow_days or [])
        if str(d.get("id") or "").strip()
    ]

    day_to_phase = load_analyst_day_phase_map(db, int(ex.id))
    active_day = (active_day_id or "").strip()
    if not active_day and day_tabs:
        active_day = day_tabs[0]["day_id"]

    active_phase = _resolve_analyst_criteria_phase_key(
        (active_phase_key or "").strip()
    ) or (active_phase_key or "").strip()
    if not active_phase and active_day:
        active_phase = (day_to_phase.get(active_day) or "").strip()
    if not active_phase and phases:
        active_phase = phases[0][0]

    if persist_day_phase and active_day and active_phase:
        set_analyst_day_phase_link(
            db, int(ex.id), day_id=active_day, phase_key=active_phase
        )
        day_to_phase = load_analyst_day_phase_map(db, int(ex.id))

    phase_label = ""
    for pk, lbl in phases:
        if pk == active_phase:
            phase_label = lbl
            break
    if not phase_label and active_phase:
        phase_label = active_phase

    phase_unit_keys = (
        unit_keys_for_evaluation_list_phase(
            db,
            int(ex.id),
            active_phase,
            day_to_phase=day_to_phase,
            flow_days=flow_days,
        )
        if active_phase
        else []
    )

    from app.views import _resolve_unit_level_key_for_criteria_label as resolve_uk

    existing_by_key: dict[str, AnalystDilemmaCriteriaUnit] = {}
    for row in criteria_units:
        uk = resolve_uk(row.label or "")
        if uk:
            existing_by_key[uk] = row

    ensured = False
    for uk in phase_unit_keys:
        if uk not in existing_by_key:
            _ensure_dilemma_unit_for_key(db, ex, uk, existing_by_key)
            ensured = True
    if ensured:
        db.commit()
        criteria_units = (
            db.query(AnalystDilemmaCriteriaUnit)
            .filter(AnalystDilemmaCriteriaUnit.exercise_id == ex.id)
            .order_by(
                AnalystDilemmaCriteriaUnit.sort_order,
                AnalystDilemmaCriteriaUnit.id,
            )
            .all()
        )
        existing_by_key = {}
        for row in criteria_units:
            uk = resolve_uk(row.label or "")
            if uk:
                existing_by_key[uk] = row

    # مثل تبويب المراحل: التوزيع من العلامات المدخلة في «تفاصيل» فقط
    # (مجموع allocated_mark) — دون سحب تلقائي من نتائج المجرى في جدول التوزيع.
    from app.views import _analyst_criteria_phase_db_keys

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

    phase_db_keys = [
        k for k in _analyst_criteria_phase_db_keys(active_phase) if (k or "").strip()
    ]
    if active_phase and active_phase not in phase_db_keys:
        phase_db_keys.append(active_phase)

    phase_key_set = {uk for uk in phase_unit_keys}
    rows: list[dict] = []
    grand_total = 0.0
    for uk in phase_unit_keys:
        unit = existing_by_key.get(uk)
        if unit is None:
            continue
        marks: list[float] = []
        for pk in phase_db_keys:
            marks.extend(marks_by_unit_phase.get((unit.id, pk), []))
        phase_total: float | None = sum(marks) if marks else None
        # نفس فكرة المراحل: الإجمالي = مجموع علامات المرحلة المعروضة
        total_mark = phase_total
        if total_mark is not None:
            grand_total += total_mark
        unit_label = label_for_unit_level_key(uk, db=db) or (unit.label or "—")
        rows.append(
            {
                "unit_id": unit.id,
                "unit_level_key": uk,
                "unit_label": unit_label,
                "phase_key": active_phase,
                "phase_label": phase_label,
                "phase_total": phase_total,
                "total_mark": total_mark,
                "allocated_pct": None,
            }
        )

    # نفس صيغة تبويب المراحل: نسبة الوحدة = إجماليها ÷ إجمالي كل الوحدات × 100
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
        "day_tabs": day_tabs,
        "active_day_id": active_day,
        "active_phase_key": active_phase,
        "active_phase_label": phase_label,
        "phase_unit_keys": list(phase_key_set),
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
    """عناصر تفاصيل المرحلة + تسميات الأيام — مثل قوائم التقييم (المراحل):

    العناوين من قوائم المجرى/المعاضل، والعلامات من المحفوظ يدوياً فقط
    (بدون سحب تلقائي للمكتسبة من المحكم).
    """
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
    for r in reaction.get("rows") or []:
        title = (r.get("list_title") or "").strip()
        if not title or title == "—" or title in seen:
            continue
        seen.add(title)
        list_titles.append(title[:1000])

    if not list_titles and saved_rows:
        for row in saved_rows:
            title = (row.criteria_text or "").strip()
            if title and title not in seen:
                seen.add(title)
                list_titles.append(title[:1000])

    # مثل المراحل: العلامة من المحفوظ فقط — لا تعبئة تلقائية من مكتسبة المحكم
    merged: list[dict] = []
    for idx, title in enumerate(list_titles):
        mark = marks_by_text.get(title)
        if mark is None and idx < len(marks_by_index):
            mark = marks_by_index[idx]
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


def collect_dilemma_acquired_for_unit_phase(
    db: Session,
    ex: Exercise,
    unit: AnalystDilemmaCriteriaUnit,
    phase_key: str,
) -> list[dict]:
    """مكتسبة قوائم تقييم المعاضل/الإجراءات لملء تلقائي (مثل autofill في المراحل)."""
    from app.views import _resolve_unit_level_key_for_criteria_label

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
    out: list[dict] = []
    seen: set[str] = set()
    for r in reaction.get("rows") or []:
        title = (r.get("list_title") or "").strip()
        if not title or title == "—" or title in seen:
            continue
        seen.add(title)
        acq = r.get("acquired")
        mx = r.get("max_mark")
        out.append(
            {
                "criteria_text": title[:1000],
                "acquired_mark": (
                    round(float(acq), 4) if isinstance(acq, (int, float)) else None
                ),
                "max_mark": (
                    round(float(mx), 4) if isinstance(mx, (int, float)) else None
                ),
            }
        )
    return out


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
