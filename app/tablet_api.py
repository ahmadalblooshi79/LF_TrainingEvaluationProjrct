# -*- coding: utf-8 -*-
"""JSON API لتطبيق تابلت المحكمين — يقرأ/يكتب مباشرة على النظام الحالي."""
from __future__ import annotations

import json
from datetime import datetime
from functools import wraps

from flask import Blueprint, g, jsonify, request, session

from app.auth import get_current_user_optional, verify_password
from app.models import Exercise, ExerciseObjective, User
from app.models.user import RoleKey
from app.permissions import (
    can_access_chief_judge_hub,
    can_access_judge_hub,
    is_system_admin,
)
from app.unit_levels_catalog import label_for_unit_level_key

bp = Blueprint("tablet_api", __name__, url_prefix="/api/tablet")


def _json_error(message: str, status: int = 400, **extra):
    body = {"ok": False, "error": message}
    body.update(extra)
    return jsonify(body), status


def _require_judge_json(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = get_current_user_optional()
        if not user:
            return _json_error("غير مسجّل الدخول", 401)
        if not can_access_judge_hub(user):
            return _json_error("لا صلاحية لمساحة المحكمين", 403)
        return fn(user, *args, **kwargs)

    return wrapper


def _exercise_for(user: User) -> Exercise | None:
    from app.views import _current_workspace_exercise

    return _current_workspace_exercise(g.db, user)


def _unit_key_for(user: User, ex: Exercise | None) -> str:
    from app.views import _judge_assigned_unit_key

    return _judge_assigned_unit_key(g.db, user, ex)


def _judge_display_name(user: User, ex: Exercise | None) -> str:
    from app.models.domain import ExerciseRosterKind, ExerciseRosterRow

    mil = (getattr(user, "username", "") or "").strip()
    if ex is not None and mil:
        jr = (
            g.db.query(ExerciseRosterRow)
            .filter(
                ExerciseRosterRow.exercise_id == ex.id,
                ExerciseRosterRow.roster_kind == ExerciseRosterKind.JUDGE.value,
                ExerciseRosterRow.military_number == mil,
            )
            .order_by(ExerciseRosterRow.sort_order, ExerciseRosterRow.id)
            .first()
        )
        if jr is not None:
            rank = (jr.rank_ar or "").strip()
            name = (jr.full_name or "").strip()
            if rank and name:
                return f"{rank} / {name}"
            if name:
                return name
    return (user.full_name or user.username or "").strip()


def _role_label(user: User, unit_key: str) -> str:
    if unit_key:
        lbl = label_for_unit_level_key(unit_key, db=g.db)
        if lbl:
            return f"محكم {lbl}" if not lbl.startswith("محكم") else lbl
    rk = (user.role_key or "").strip()
    if rk == RoleKey.CHIEF_JUDGE.value:
        return "كبير المحكمين"
    return "محكم"


def _period_label(ex: Exercise) -> str:
    s = getattr(ex, "planned_start", None)
    e = getattr(ex, "planned_end", None)
    def _fmt(v) -> str:
        if v is None:
            return ""
        try:
            return v.strftime("%Y-%m-%d")
        except Exception:
            return str(v)
    ss, ee = _fmt(s), _fmt(e)
    if ss and ee:
        return f"{ss} — {ee}"
    return ss or ee or ""


def _serialize_user_bundle(user: User, ex: Exercise | None) -> dict:
    uk = _unit_key_for(user, ex)
    return {
        "user": {
            "id": int(user.id),
            "username": user.username,
            "full_name": user.full_name or "",
            "judge_display_name": _judge_display_name(user, ex),
            "role_key": user.role_key or "",
            "role_label": _role_label(user, uk),
            "is_chief_judge": can_access_chief_judge_hub(user),
            "is_admin": is_system_admin(user),
        },
        "exercise": None
        if ex is None
        else {
            "id": int(ex.id),
            "name": (ex.title or "").strip(),
            "code": (ex.code or "").strip(),
            "location": (ex.location_label or "").strip(),
            "start_date": _period_label(ex).split(" — ")[0] if ex.planned_start else "",
            "end_date": _period_label(ex).split(" — ")[-1] if ex.planned_end else "",
            "period_label": _period_label(ex),
            "type_label": (
                (ex.exercise_type_level_text or "").strip()
                or (ex.exercise_type or "").strip()
            ),
        },
        "unit_key": uk,
        "unit_label": label_for_unit_level_key(uk, db=g.db) if uk else "",
        "server_time": datetime.utcnow().isoformat() + "Z",
    }


def _as_text(v) -> str:
    if v is None:
        return ""
    if isinstance(v, datetime):
        try:
            return v.strftime("%Y-%m-%d %H:%M")
        except Exception:
            return str(v)
    return str(v).strip()


def _safe_row(r: dict) -> dict:
    return {
        "id": r.get("item_id") or r.get("slot_id") or r.get("slot_index") or r.get("id"),
        "slot_index": r.get("slot_index"),
        "slot_id": r.get("slot_id"),
        "item_id": r.get("item_id"),
        "title": _as_text(r.get("item_title") or r.get("title") or ""),
        "date": _as_text(r.get("dt") or r.get("date") or ""),
        "seq": r.get("seq") or r.get("sort_order") or "",
        "grade_label": _as_text(r.get("grade_label") or ""),
        "delivery_dt": _as_text(r.get("delivery_dt") or r.get("dispatch_label") or ""),
        "status_done": bool(r.get("status_done")),
        "status_label": _as_text(
            r.get("status_label") or ("منجز" if r.get("status_done") else "غير منجز")
        ),
        "unit_key": _as_text(r.get("unit_key") or r.get("unit") or ""),
        "unit_label": _as_text(r.get("unit_label") or ""),
        "phase_key": _as_text(r.get("phase_key") or ""),
        "list_type": _as_text(r.get("list_type_kind") or r.get("list_type") or ""),
        "open_href": _as_text(r.get("open_href") or ""),
        "workflow_label": _as_text(r.get("workflow_label") or ""),
        "dilemma_no": r.get("dilemma_no"),
        "node_id": r.get("node_id"),
    }


@bp.get("/health")
def tablet_health():
    return jsonify(
        {"ok": True, "service": "tablet", "time": datetime.utcnow().isoformat() + "Z"}
    )


@bp.post("/auth/login")
def tablet_login():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or request.form.get("username") or "").strip()
    password = data.get("password") or request.form.get("password") or ""
    if not username or not password:
        return _json_error("أدخل اسم المستخدم وكلمة المرور", 400)
    user = (
        g.db.query(User)
        .filter(User.username == username, User.is_active == True)  # noqa: E712
        .first()
    )
    if user is None or not verify_password(password, user.password_hash or ""):
        return _json_error("بيانات الدخول غير صحيحة", 401)
    if not can_access_judge_hub(user):
        return _json_error("هذا الحساب لا يملك صلاحية تطبيق المحكمين", 403)
    session.clear()
    session["user_id"] = int(user.id)
    session.permanent = True
    ex = _exercise_for(user)
    return jsonify({"ok": True, **_serialize_user_bundle(user, ex)})


@bp.post("/auth/logout")
def tablet_logout():
    session.clear()
    return jsonify({"ok": True})


@bp.get("/me")
@_require_judge_json
def tablet_me(user: User):
    return jsonify({"ok": True, **_serialize_user_bundle(user, _exercise_for(user))})


@bp.get("/home")
@_require_judge_json
def tablet_home(user: User):
    from app.views import (
        _build_incomplete_evaluations_report,
        _collect_all_eval_status_rows_flat,
    )

    ex = _exercise_for(user)
    bundle = _serialize_user_bundle(user, ex)
    incomplete = _build_incomplete_evaluations_report(g.db, user, role="judge")
    incomplete_rows = [_safe_row(r) for r in (incomplete.get("incomplete_rows") or [])]
    incomplete_count = int(incomplete.get("incomplete_count") or 0)

    total = 0
    done = 0
    if ex is not None:
        uk = bundle.get("unit_key") or None
        all_rows = _collect_all_eval_status_rows_flat(
            g.db,
            exercise=ex,
            unit_filter=uk or None,
            eval_open_endpoint="views.judge_evaluation_list_file_viewer",
            planner_open_endpoint="views.judge_planner_flow_materials_action_evaluate",
            planner_open_uses_slot=True,
        )
        total = len(all_rows)
        done = sum(1 for r in all_rows if r.get("status_done"))
    pct = int(round((done * 100.0 / total), 0)) if total else 0

    return jsonify(
        {
            "ok": True,
            **bundle,
            "stats": {
                "completion_pct": pct,
                "completed_count": done,
                "total_count": total,
                "incomplete_count": incomplete_count,
                "completed_lists": done,
                "incomplete_lists": max(total - done, 0),
            },
            "incomplete_tasks": incomplete_rows[:50],
            "menu": [
                {"id": "flow", "title": "مجرى الأحداث والمعاضل", "route": "/flow"},
                {
                    "id": "action_eval",
                    "title": "قوائم تقييم الإجراءات",
                    "route": "/action-eval",
                },
                {
                    "id": "evaluation_lists",
                    "title": "قوائم التقييم",
                    "route": "/evaluation-lists",
                },
                {
                    "id": "objectives",
                    "title": "الأهداف التدريبية",
                    "route": "/objectives",
                },
            ],
        }
    )


@bp.get("/flow")
@_require_judge_json
def tablet_flow(user: User):
    from app.views import (
        _exercise_flow_bundle_with_content,
        _flow_table_fields_from_bundle,
        _judge_assigned_planner_bundle,
    )

    ex = _exercise_for(user)
    if ex is None:
        return _json_error("لا يوجد تمرين نشط", 404)
    uk = _unit_key_for(user, ex)
    bundle = _judge_assigned_planner_bundle(g.db, user, ex)
    if bundle is None:
        bundle = _exercise_flow_bundle_with_content(g.db, ex.id)
    fields = _flow_table_fields_from_bundle(bundle)
    days = fields.get("flow_table_days") or []
    active = (
        request.args.get("day") or fields.get("flow_table_active_day_id") or ""
    ).strip()
    if not active and days:
        active = str(days[0].get("id") or "")
    rows = []
    for d in days:
        if str(d.get("id") or "") == active:
            rows = list(d.get("rows") or [])
            break
    if not rows:
        rows = list(fields.get("flow_table_rows") or [])

    def _row_out(r: dict, idx: int) -> dict:
        kind = (r.get("kind") or "row").strip().lower()
        return {
            "seq": idx + 1,
            "kind": kind,
            "time": (r.get("time") or r.get("timing") or "").strip(),
            "text": (r.get("text") or r.get("description") or "").strip(),
            "assignee": (r.get("assignee") or "").strip(),
            "method": (r.get("method") or r.get("imposition") or "").strip(),
            "expected": (r.get("expected") or r.get("expected_reaction") or "").strip(),
            "tone": "event"
            if kind == "event"
            else ("dilemma" if kind == "dilemma" else "row"),
        }

    return jsonify(
        {
            "ok": True,
            "exercise_id": int(ex.id),
            "unit_key": uk,
            "unit_label": label_for_unit_level_key(uk, db=g.db) if uk else "",
            "title": (fields.get("flow_table_title") or "").strip()
            or f"مجرى أحداث ومعاضل {(ex.title or '').strip()}",
            "active_day_id": active,
            "days": [
                {
                    "id": str(d.get("id") or ""),
                    "label": str(d.get("label") or d.get("id") or ""),
                    "note": str(d.get("note") or ""),
                    "phase_key": str(d.get("phase_key") or ""),
                }
                for d in days
            ],
            "rows": [_row_out(r, i) for i, r in enumerate(rows)],
            "readonly": True,
        }
    )


@bp.get("/action-eval")
@_require_judge_json
def tablet_action_eval_lists(user: User):
    from app.action_eval_ibank_sync import (
        build_judge_action_eval_display_groups,
        collect_flow_day_tabs_for_exercise,
        effective_action_eval_phase_keys,
    )
    from app.exercise_phase_catalog import default_exercise_phase_key, normalize_exercise_phase
    from app.views import _enrich_judge_action_eval_groups

    ex = _exercise_for(user)
    if ex is None:
        return _json_error("لا يوجد تمرين نشط", 404)
    uk = _unit_key_for(user, ex)
    day_id = (request.args.get("day") or "").strip()
    phase = normalize_exercise_phase(
        (request.args.get("phase") or "").strip() or default_exercise_phase_key()
    )
    if not phase:
        for pk in effective_action_eval_phase_keys(g.db, roster_units=set()):
            if (pk or "").strip():
                phase = pk
                break
    day_tabs = collect_flow_day_tabs_for_exercise(
        g.db, exercise_id=int(ex.id), phase_key=phase or ""
    )
    if not day_id and day_tabs:
        day_id = str(day_tabs[0].get("id") or "")
    groups, meta = build_judge_action_eval_display_groups(
        g.db,
        exercise_id=int(ex.id),
        phase_key=phase or None,
        flow_day_id=day_id or None,
        restrict_unit_key=uk or None,
    )
    groups = _enrich_judge_action_eval_groups(g.db, ex, groups, flow_qs={})
    lists: list[dict] = []
    for g0 in groups:
        for folder in g0.get("list_folder_groups") or []:
            for row in folder.get("rows") or []:
                lists.append(
                    _safe_row({**row, "unit_key": g0.get("unit_key") or uk})
                )

    return jsonify(
        {
            "ok": True,
            "day_id": day_id,
            "day_tabs": day_tabs,
            "phase_key": phase,
            "unit_key": uk,
            "lists": lists,
            "meta": meta,
        }
    )


@bp.get("/action-eval/<int:slot>")
@_require_judge_json
def tablet_action_eval_detail(user: User, slot: int):
    from werkzeug.exceptions import Forbidden, HTTPException

    from app.models.domain import (
        ExercisePlannerFlowBundle,
        ExercisePlannerFlowBundleActionEval,
    )
    from app.views import (
        _evaluation_sheet_view_context,
        _judge_assigned_unit_key,
        _judge_planner_flow_action_bundle_row,
        _planner_blob_display_filename,
        _planner_bundle_eval_canonical_saved,
        _planner_bundle_file_abspath,
        _planner_flow_eval_list_viewer_ctx,
        _saved_payload_aligned_with_eval_rows,
    )

    ex = _exercise_for(user)
    if ex is None:
        return _json_error("لا يوجد تمرين نشط", 404)

    pair = None
    try:
        pair = _judge_planner_flow_action_bundle_row(g.db, user, ex, slot)
    except Forbidden:
        pair = None
    except HTTPException as exc:
        if int(getattr(exc, "code", 0) or 0) == 403:
            pair = None
        else:
            raise

    # حساب بلا وحدة مخصصة / فشل التحقق: افتح بالـ slot_index أو slot_id مباشرة
    if pair is None:
        action_row = (
            g.db.query(ExercisePlannerFlowBundleActionEval)
            .join(
                ExercisePlannerFlowBundle,
                ExercisePlannerFlowBundle.id
                == ExercisePlannerFlowBundleActionEval.bundle_id,
            )
            .filter(
                ExercisePlannerFlowBundle.exercise_id == int(ex.id),
                ExercisePlannerFlowBundleActionEval.slot_index == int(slot),
            )
            .order_by(ExercisePlannerFlowBundleActionEval.id)
            .first()
        )
        if action_row is None:
            action_row = g.db.get(ExercisePlannerFlowBundleActionEval, int(slot))
            if action_row is not None:
                bundle0 = g.db.get(ExercisePlannerFlowBundle, int(action_row.bundle_id))
                if bundle0 is None or int(bundle0.exercise_id) != int(ex.id):
                    action_row = None
        if action_row is None or not (action_row.file_relpath or "").strip():
            return _json_error("القائمة غير موجودة", 404)
        bundle = g.db.get(ExercisePlannerFlowBundle, int(action_row.bundle_id))
        if bundle is None:
            return _json_error("القائمة غير موجودة", 404)
        assigned = (_judge_assigned_unit_key(g.db, user, ex) or "").strip()
        if assigned and (bundle.unit_level_key or "").strip() not in ("", assigned):
            return _json_error("هذه القائمة خارج نطاق وحدتك", 403)
        pair = (bundle, action_row)

    bundle, action_row = pair
    path = _planner_bundle_file_abspath(action_row.file_relpath)
    if path is None:
        return _json_error("ملف القائمة غير موجود على السيرفر", 404)
    ev = _evaluation_sheet_view_context(path)
    canon = _planner_bundle_eval_canonical_saved(g.db, ex.id, action_row.id)
    saved_payload: dict = {}
    if canon is not None and (canon.payload_json or "").strip():
        try:
            p = json.loads(canon.payload_json)
            saved_payload = p if isinstance(p, dict) else {}
        except Exception:
            saved_payload = {}
    saved_payload = _saved_payload_aligned_with_eval_rows(
        saved_payload, ev.get("eval_rows")
    )
    wf = _planner_flow_eval_list_viewer_ctx(user, canon)
    title = _planner_blob_display_filename(
        stored_title=action_row.title or "",
        relpath=action_row.file_relpath or "",
        fallback=f"قائمة تقييم إجراءات — {slot}",
    ).strip()
    return jsonify(
        {
            "ok": True,
            "kind": "action_eval",
            "slot": int(action_row.slot_index or slot),
            "slot_id": int(action_row.id),
            "title": title,
            "unit_key": bundle.unit_level_key,
            "unit_label": (bundle.unit_level_label or "").strip()
            or label_for_unit_level_key(bundle.unit_level_key, db=g.db),
            "eval_rows": ev.get("eval_rows") or [],
            "eval_structured": bool(ev.get("eval_structured")),
            "acquired_options": ev.get("acquired_options") or [],
            "saved_payload": saved_payload,
            "can_edit": bool(wf.get("eval_can_edit")),
            "can_approve": bool(wf.get("show_eval_approve")),
            "is_approved": bool(wf.get("saved_is_approved")),
            "workflow": {
                "label": wf.get("workflow_label") or "",
                "reopened": bool(wf.get("eval_reopened")),
            },
        }
    )


@bp.put("/action-eval/<int:slot>/results")
@_require_judge_json
def tablet_action_eval_save(user: User, slot: int):
    from app.views import (
        _judge_planner_flow_action_bundle_row,
        _planner_bundle_eval_commit_payload_save,
    )

    ex = _exercise_for(user)
    pair = _judge_planner_flow_action_bundle_row(g.db, user, ex, slot)
    if pair is None or ex is None:
        return _json_error("القائمة غير موجودة", 404)
    _, action_row = pair
    data = request.get_json(silent=True) or {}
    payload = data.get("payload") if isinstance(data.get("payload"), dict) else data
    if not isinstance(payload, dict):
        return _json_error("حمولة غير صالحة")
    raw = json.dumps(payload, ensure_ascii=False)
    try:
        _planner_bundle_eval_commit_payload_save(
            g.db, user=user, action_row=action_row, current_exercise=ex, raw=raw
        )
    except Exception as exc:
        return _json_error(str(exc) or "فشل الحفظ", 400)
    return jsonify({"ok": True, "saved": True})


@bp.post("/action-eval/<int:slot>/approve")
@_require_judge_json
def tablet_action_eval_approve(user: User, slot: int):
    from app.evaluation_workflow import apply_judge_approve, eval_judge_can_edit
    from app.views import (
        _judge_planner_flow_action_bundle_row,
        _planner_bundle_eval_canonical_saved,
    )

    ex = _exercise_for(user)
    pair = _judge_planner_flow_action_bundle_row(g.db, user, ex, slot)
    if pair is None or ex is None:
        return _json_error("القائمة غير موجودة", 404)
    _, action_row = pair
    saved = _planner_bundle_eval_canonical_saved(g.db, ex.id, action_row.id)
    if saved is None:
        return _json_error("احفظ النتائج قبل الاعتماد", 400)
    if not eval_judge_can_edit(saved):
        return _json_error("لا يمكن اعتماد هذه القائمة حالياً", 403)
    apply_judge_approve(saved, getattr(user, "id", None))
    g.db.commit()
    return jsonify({"ok": True, "approved": True})


@bp.get("/evaluation-lists")
@_require_judge_json
def tablet_evaluation_lists(user: User):
    from app.exercise_phase_catalog import (
        default_exercise_phase_key,
        exercise_phase_keys,
        exercise_phase_label,
        normalize_exercise_phase,
    )
    from app.models.domain import EvaluationListPdfItem
    from app.views import (
        _evaluation_canonical_map_for_items,
        _judge_evaluation_list_unit_levels,
        build_evaluation_list_row,
        filter_evaluation_items_by_phase,
    )

    ex = _exercise_for(user)
    if ex is None:
        return _json_error("لا يوجد تمرين نشط", 404)
    units = _judge_evaluation_list_unit_levels(g.db, user, ex)
    # إن لم تُخصَّص وحدة للمحكم: اعرض الوحدات التي لها قوائم فعلياً
    if not units:
        from app.unit_levels_catalog import unit_level_row

        seen: set[str] = set()
        units = []
        for it0 in (
            g.db.query(EvaluationListPdfItem)
            .filter(EvaluationListPdfItem.exercise_id == int(ex.id))
            .order_by(EvaluationListPdfItem.sort_order, EvaluationListPdfItem.id)
            .all()
        ):
            k = (it0.unit_level_key or "").strip()
            if not k or k in seen:
                continue
            seen.add(k)
            row_u = unit_level_row(k)
            if row_u:
                units.append(row_u)
            else:
                units.append(
                    {
                        "key": k,
                        "label": (it0.unit_level_label or label_for_unit_level_key(k, db=g.db) or k).strip(),
                    }
                )
    uk = (request.args.get("unit_key") or "").strip()
    if not uk and units:
        uk = units[0]["key"]
    phase = normalize_exercise_phase(
        (request.args.get("phase") or "").strip() or default_exercise_phase_key()
    )
    q = g.db.query(EvaluationListPdfItem).filter(
        EvaluationListPdfItem.exercise_id == int(ex.id)
    )
    if uk:
        q = q.filter(EvaluationListPdfItem.unit_level_key == uk)
    items = q.order_by(EvaluationListPdfItem.sort_order, EvaluationListPdfItem.id).all()
    if phase:
        items = filter_evaluation_items_by_phase(items, phase)
    # إن كانت المرحلة الافتراضية فارغة ولم يُطلب phase صراحةً — انتقل لأول مرحلة فيها عناصر
    if not items and not (request.args.get("phase") or "").strip():
        for pk in exercise_phase_keys():
            if pk == phase:
                continue
            q2 = g.db.query(EvaluationListPdfItem).filter(
                EvaluationListPdfItem.exercise_id == int(ex.id)
            )
            if uk:
                q2 = q2.filter(EvaluationListPdfItem.unit_level_key == uk)
            cand = filter_evaluation_items_by_phase(
                q2.order_by(EvaluationListPdfItem.sort_order, EvaluationListPdfItem.id).all(),
                pk,
            )
            if cand:
                phase = pk
                items = cand
                break
    item_ids = [int(it.id) for it in items]
    canonical_by_item = _evaluation_canonical_map_for_items(g.db, ex.id, item_ids)
    lists = []
    for it in items:
        s = canonical_by_item.get(int(it.id))
        item_uk = (it.unit_level_key or uk or "").strip()
        row = build_evaluation_list_row(
            item=it,
            saved=s,
            exercise=ex,
            open_href=f"/api/tablet/evaluation-lists/{item_uk}/{int(it.id)}",
        )
        lists.append(
            _safe_row(
                {
                    **row,
                    "unit_key": item_uk,
                    "unit_label": (it.unit_level_label or "").strip()
                    or label_for_unit_level_key(item_uk, db=g.db),
                    "phase_key": (it.exercise_phase or phase or "").strip(),
                }
            )
        )
    phase_tabs = [
        {"key": k, "label": exercise_phase_label(k)} for k in exercise_phase_keys()
    ]
    return jsonify(
        {
            "ok": True,
            "unit_key": uk,
            "unit_levels": units,
            "phase_key": phase,
            "phase_tabs": phase_tabs,
            "lists": lists,
        }
    )


@bp.get("/evaluation-lists/<unit_key>/<int:item_id>")
@_require_judge_json
def tablet_evaluation_list_detail(user: User, unit_key: str, item_id: int):
    from werkzeug.exceptions import Forbidden, HTTPException

    from app.models.domain import EvaluationListPdfItem
    from app.views import (
        _enforce_judge_unit_scope,
        _eval_list_viewer_ctx,
        _evaluation_canonical_saved_row,
        _evaluation_list_file_abspath,
        _evaluation_sheet_view_context,
        _judge_assigned_unit_key,
        _saved_payload_aligned_with_eval_rows,
    )

    ex = _exercise_for(user)
    if ex is None:
        return _json_error("لا يوجد تمرين نشط", 404)
    item = g.db.get(EvaluationListPdfItem, int(item_id))
    if item is None or int(item.exercise_id) != int(ex.id):
        return _json_error("القائمة غير موجودة", 404)
    item_uk = (item.unit_level_key or "").strip()
    req_uk = (unit_key or "").strip()
    if req_uk not in ("", "_") and item_uk and req_uk != item_uk:
        return _json_error("مستوى الوحدة غير مطابق", 403)
    effective_uk = item_uk or (req_uk if req_uk not in ("", "_") else "")
    try:
        if effective_uk:
            _enforce_judge_unit_scope(g.db, user, ex, effective_uk)
    except Forbidden:
        assigned = (_judge_assigned_unit_key(g.db, user, ex) or "").strip()
        if assigned and effective_uk and assigned != effective_uk:
            return _json_error("هذه القائمة خارج نطاق وحدتك", 403)
    except HTTPException as exc:
        if int(getattr(exc, "code", 0) or 0) != 403:
            raise
        assigned = (_judge_assigned_unit_key(g.db, user, ex) or "").strip()
        if assigned and effective_uk and assigned != effective_uk:
            return _json_error("هذه القائمة خارج نطاق وحدتك", 403)
    path = _evaluation_list_file_abspath((item.pdf_relpath or "").strip())
    if path is None:
        return _json_error("ملف القائمة غير موجود على السيرفر", 404)
    ev = _evaluation_sheet_view_context(path)
    saved = _evaluation_canonical_saved_row(g.db, ex.id, item.id)
    saved_payload: dict = {}
    if saved is not None and (saved.payload_json or "").strip():
        try:
            p = json.loads(saved.payload_json)
            saved_payload = p if isinstance(p, dict) else {}
        except Exception:
            saved_payload = {}
    saved_payload = _saved_payload_aligned_with_eval_rows(
        saved_payload, ev.get("eval_rows")
    )
    wf = _eval_list_viewer_ctx(user, saved)
    return jsonify(
        {
            "ok": True,
            "kind": "evaluation_list",
            "item_id": int(item.id),
            "title": (item.text or "").strip(),
            "unit_key": effective_uk,
            "unit_label": label_for_unit_level_key(effective_uk, db=g.db),
            "phase_key": (item.exercise_phase or "").strip(),
            "eval_rows": ev.get("eval_rows") or [],
            "eval_structured": bool(ev.get("eval_structured")),
            "acquired_options": ev.get("acquired_options") or [],
            "saved_payload": saved_payload,
            "can_edit": bool(wf.get("eval_can_edit")),
            "can_approve": bool(wf.get("show_eval_approve")),
            "is_approved": bool(wf.get("saved_is_approved")),
            "workflow": {
                "label": wf.get("workflow_label") or "",
                "reopened": bool(wf.get("eval_reopened")),
            },
        }
    )


@bp.put("/evaluation-lists/<unit_key>/<int:item_id>/results")
@_require_judge_json
def tablet_evaluation_list_save(user: User, unit_key: str, item_id: int):
    from werkzeug.exceptions import Forbidden, HTTPException

    from app.models.domain import EvaluationListPdfItem
    from app.views import (
        _enforce_judge_unit_scope,
        _evaluation_commit_payload_save,
        _judge_assigned_unit_key,
    )

    ex = _exercise_for(user)
    if ex is None:
        return _json_error("لا يوجد تمرين نشط", 404)
    item = g.db.get(EvaluationListPdfItem, int(item_id))
    if item is None or int(item.exercise_id) != int(ex.id):
        return _json_error("القائمة غير موجودة", 404)
    effective_uk = (item.unit_level_key or unit_key or "").strip()
    try:
        if effective_uk and effective_uk not in ("", "_"):
            _enforce_judge_unit_scope(g.db, user, ex, effective_uk)
    except Forbidden:
        assigned = (_judge_assigned_unit_key(g.db, user, ex) or "").strip()
        if assigned and effective_uk and assigned != effective_uk:
            return _json_error("هذه القائمة خارج نطاق وحدتك", 403)
    except HTTPException as exc:
        if int(getattr(exc, "code", 0) or 0) != 403:
            raise
        assigned = (_judge_assigned_unit_key(g.db, user, ex) or "").strip()
        if assigned and effective_uk and assigned != effective_uk:
            return _json_error("هذه القائمة خارج نطاق وحدتك", 403)
    data = request.get_json(silent=True) or {}
    payload = data.get("payload") if isinstance(data.get("payload"), dict) else data
    raw = json.dumps(payload, ensure_ascii=False)
    try:
        _evaluation_commit_payload_save(
            g.db, user=user, item=item, current_exercise=ex, raw=raw
        )
    except Exception as exc:
        return _json_error(str(exc) or "فشل الحفظ", 400)
    return jsonify({"ok": True, "saved": True})


@bp.post("/evaluation-lists/<unit_key>/<int:item_id>/approve")
@_require_judge_json
def tablet_evaluation_list_approve(user: User, unit_key: str, item_id: int):
    from werkzeug.exceptions import Forbidden, HTTPException

    from app.evaluation_workflow import apply_judge_approve, eval_judge_can_edit
    from app.models.domain import EvaluationListPdfItem
    from app.views import (
        _enforce_judge_unit_scope,
        _evaluation_canonical_saved_row,
        _judge_assigned_unit_key,
    )

    ex = _exercise_for(user)
    if ex is None:
        return _json_error("لا يوجد تمرين نشط", 404)
    item = g.db.get(EvaluationListPdfItem, int(item_id))
    if item is None or int(item.exercise_id) != int(ex.id):
        return _json_error("القائمة غير موجودة", 404)
    effective_uk = (item.unit_level_key or unit_key or "").strip()
    try:
        if effective_uk and effective_uk not in ("", "_"):
            _enforce_judge_unit_scope(g.db, user, ex, effective_uk)
    except Forbidden:
        assigned = (_judge_assigned_unit_key(g.db, user, ex) or "").strip()
        if assigned and effective_uk and assigned != effective_uk:
            return _json_error("هذه القائمة خارج نطاق وحدتك", 403)
    except HTTPException as exc:
        if int(getattr(exc, "code", 0) or 0) != 403:
            raise
        assigned = (_judge_assigned_unit_key(g.db, user, ex) or "").strip()
        if assigned and effective_uk and assigned != effective_uk:
            return _json_error("هذه القائمة خارج نطاق وحدتك", 403)
    saved = _evaluation_canonical_saved_row(g.db, ex.id, item.id)
    if saved is None:
        return _json_error("احفظ النتائج قبل الاعتماد", 400)
    if not eval_judge_can_edit(saved):
        return _json_error("لا يمكن اعتماد هذه القائمة حالياً", 403)
    apply_judge_approve(saved, getattr(user, "id", None))
    g.db.commit()
    return jsonify({"ok": True, "approved": True})


@bp.get("/objectives")
@_require_judge_json
def tablet_objectives(user: User):
    ex = _exercise_for(user)
    if ex is None:
        return _json_error("لا يوجد تمرين نشط", 404)
    rows = (
        g.db.query(ExerciseObjective)
        .filter(ExerciseObjective.exercise_id == int(ex.id))
        .order_by(ExerciseObjective.sort_order, ExerciseObjective.id)
        .all()
    )
    return jsonify(
        {
            "ok": True,
            "exercise_id": int(ex.id),
            "exercise_name": (ex.title or "").strip(),
            "objectives": [
                {
                    "id": int(r.id),
                    "sort_order": int(r.sort_order or 0),
                    "text": r.text or "",
                }
                for r in rows
            ],
        }
    )


@bp.get("/incomplete")
@_require_judge_json
def tablet_incomplete(user: User):
    from app.views import _build_incomplete_evaluations_report

    report = _build_incomplete_evaluations_report(g.db, user, role="judge")
    return jsonify(
        {
            "ok": True,
            "count": int(report.get("incomplete_count") or 0),
            "tasks": [_safe_row(r) for r in (report.get("incomplete_rows") or [])],
        }
    )


@bp.get("/bootstrap")
@_require_judge_json
def tablet_bootstrap(user: User):
    """حزمة أولية للتخزين المحلي عند الدخول أو قبل Offline."""
    from app.views import (
        _build_incomplete_evaluations_report,
        _collect_all_eval_status_rows_flat,
    )

    ex = _exercise_for(user)
    me = _serialize_user_bundle(user, ex)
    incomplete = _build_incomplete_evaluations_report(g.db, user, role="judge")
    incomplete_rows = [_safe_row(r) for r in (incomplete.get("incomplete_rows") or [])]
    incomplete_count = int(incomplete.get("incomplete_count") or 0)

    objectives = []
    if ex is not None:
        objectives = (
            g.db.query(ExerciseObjective)
            .filter(ExerciseObjective.exercise_id == int(ex.id))
            .order_by(ExerciseObjective.sort_order, ExerciseObjective.id)
            .all()
        )

    total = 0
    done = 0
    if ex is not None:
        uk = me.get("unit_key") or None
        all_rows = _collect_all_eval_status_rows_flat(
            g.db,
            exercise=ex,
            unit_filter=uk or None,
            eval_open_endpoint="views.judge_evaluation_list_file_viewer",
            planner_open_endpoint="views.judge_planner_flow_materials_action_evaluate",
            planner_open_uses_slot=True,
        )
        total = len(all_rows)
        done = sum(1 for r in all_rows if r.get("status_done"))
    pct = int(round((done * 100.0 / total), 0)) if total else 0

    home_payload = {
        "ok": True,
        **me,
        "stats": {
            "completion_pct": pct,
            "completed_count": done,
            "total_count": total,
            "incomplete_count": incomplete_count,
            "completed_lists": done,
            "incomplete_lists": max(total - done, 0),
        },
        "incomplete_tasks": incomplete_rows[:50],
        "menu": [
            {"id": "flow", "title": "مجرى الأحداث والمعاضل", "route": "/flow"},
            {
                "id": "action_eval",
                "title": "قوائم تقييم الإجراءات",
                "route": "/action-eval",
            },
            {
                "id": "evaluation_lists",
                "title": "قوائم التقييم",
                "route": "/evaluation-lists",
            },
            {
                "id": "objectives",
                "title": "الأهداف التدريبية",
                "route": "/objectives",
            },
        ],
    }

    return jsonify(
        {
            "ok": True,
            **me,
            "home": home_payload,
            "incomplete_tasks": incomplete_rows,
            "objectives": [
                {
                    "id": int(r.id),
                    "sort_order": int(r.sort_order or 0),
                    "text": r.text or "",
                }
                for r in objectives
            ],
            "cached_at": datetime.utcnow().isoformat() + "Z",
        }
    )


@bp.post("/media/criterion")
@_require_judge_json
def tablet_media_upload(user: User):
    """رفع صورة/فيديو لعنصر تقييم — يغلف مسار النظام الحالي."""
    from app.views import eval_criterion_media_upload

    return eval_criterion_media_upload()
