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
    can_access_control_hub,
    can_access_judge_hub,
    can_plan_exercises,
    can_view_notifications_log,
    is_judge,
    is_system_admin,
)
from app.unit_levels_catalog import label_for_unit_level_key

bp = Blueprint("tablet_api", __name__, url_prefix="/api/tablet")

_TABLET_MAIN_MENU = [
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
        "id": "positives_negatives",
        "title": "الإيجابيات والسلبيات",
        "route": "/positives-negatives",
    },
    {
        "id": "objectives",
        "title": "الأهداف التدريبية",
        "route": "/objectives",
    },
]


def _json_error(message: str, status: int = 400, **extra):
    body = {"ok": False, "error": message}
    body.update(extra)
    return jsonify(body), status


def _client_op_id_from_request(data: dict | None = None) -> str:
    hdr = (
        request.headers.get("Idempotency-Key")
        or request.headers.get("X-Client-Op-Id")
        or ""
    ).strip()
    if hdr:
        return hdr[:120]
    if isinstance(data, dict):
        return str(data.get("client_op_id") or "").strip()[:120]
    form_id = (request.form.get("client_op_id") or "").strip()
    return form_id[:120]


def _idempotent_response(user: User, client_op_id: str):
    """إن وُجدت نفس العملية مسبقاً لنفس المستخدم — أعد النتيجة المخزّنة."""
    if not client_op_id:
        return None
    from app.models.domain import TabletClientOp

    row = (
        g.db.query(TabletClientOp)
        .filter(
            TabletClientOp.user_id == int(user.id),
            TabletClientOp.client_op_id == client_op_id,
        )
        .first()
    )
    if row is None:
        return None
    try:
        payload = json.loads(row.response_json or "{}")
    except Exception:
        payload = {"ok": True, "idempotent_replay": True}
    if not isinstance(payload, dict):
        payload = {"ok": True, "data": payload}
    payload["idempotent_replay"] = True
    return jsonify(payload)


def _record_client_op(
    user: User,
    *,
    client_op_id: str,
    op_type: str,
    path: str,
    response_body: dict,
    exercise_id: int | None = None,
) -> None:
    if not client_op_id:
        return
    from app.models.domain import TabletClientOp

    existing = (
        g.db.query(TabletClientOp)
        .filter(
            TabletClientOp.user_id == int(user.id),
            TabletClientOp.client_op_id == client_op_id,
        )
        .first()
    )
    if existing is not None:
        return
    g.db.add(
        TabletClientOp(
            user_id=int(user.id),
            exercise_id=int(exercise_id) if exercise_id else None,
            client_op_id=client_op_id[:120],
            op_type=(op_type or "")[:64],
            path=(path or "")[:400],
            response_json=json.dumps(response_body, ensure_ascii=False),
        )
    )
    try:
        g.db.commit()
    except Exception:
        g.db.rollback()


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
                (ex.exercise_type or "").strip()
                or (ex.exercise_type_level_text or "").strip()
            ),
            "level_label": (ex.exercise_level or "").strip(),
            "trained_unit": (ex.trained_unit or "").strip(),
            "mission_label": (ex.mission_label or "").strip(),
            "exercise_type_level_text": (ex.exercise_type_level_text or "").strip(),
            "exercise_purpose": (getattr(ex, "exercise_purpose", None) or "").strip(),
            "exercise_participants": (getattr(ex, "exercise_participants", None) or "").strip(),
            "general_idea_text": (getattr(ex, "general_idea_text", None) or "").strip(),
            "specific_idea_text": (getattr(ex, "specific_idea_text", None) or "").strip(),
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
    dispatch = _as_text(r.get("dispatch_label") or r.get("workflow_label") or "")
    return {
        "id": r.get("item_id") or r.get("slot_id") or r.get("slot_index") or r.get("id"),
        "slot_index": r.get("slot_index"),
        "slot_id": r.get("slot_id"),
        "item_id": r.get("item_id"),
        "title": _as_text(r.get("item_title") or r.get("title") or ""),
        "date": _as_text(r.get("dt") or r.get("date") or ""),
        "seq": r.get("seq") or r.get("sort_order") or "",
        "grade_label": _as_text(r.get("grade_label") or ""),
        "delivery_dt": _as_text(r.get("delivery_dt") or ""),
        "status_done": bool(r.get("status_done")),
        "status_label": _as_text(
            r.get("status_label") or ("منجز" if r.get("status_done") else "غير منجز")
        ),
        "unit_key": _as_text(r.get("unit_key") or r.get("unit") or ""),
        "unit_label": _as_text(r.get("unit_label") or ""),
        "phase_key": _as_text(r.get("phase_key") or ""),
        "list_type": _as_text(r.get("list_type_kind") or r.get("list_type") or ""),
        "list_type_label": _as_text(
            r.get("list_type_label")
            or (
                "قائمة التقييم"
                if (r.get("list_type_kind") or "") == "judge_eval"
                else (
                    "قائمة المعاضل"
                    if (r.get("list_type_kind") or "") == "planner_flow_action"
                    else ""
                )
            )
        ),
        "open_href": _as_text(r.get("open_href") or ""),
        "workflow_label": dispatch,
        "dispatch_label": dispatch,
        "row_tone": _as_text(r.get("row_tone") or ""),
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
            "menu": list(_TABLET_MAIN_MENU),
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
        # مع يوم محدد: نطاق اليوم هو المرجع بغض النظر عن مرحلة التخزين.
        phase_key=None if day_id else (phase or None),
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
                "label": (wf.get("eval_workflow_label") or wf.get("workflow_label") or ""),
                "reopened": bool(
                    wf.get("saved_reopened_for_judge") or wf.get("eval_reopened")
                ),
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

    data = request.get_json(silent=True) or {}
    client_op_id = _client_op_id_from_request(data)
    replay = _idempotent_response(user, client_op_id)
    if replay is not None:
        return replay

    ex = _exercise_for(user)
    pair = _judge_planner_flow_action_bundle_row(g.db, user, ex, slot)
    if pair is None or ex is None:
        return _json_error("القائمة غير موجودة", 404)
    _, action_row = pair
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
    body = {"ok": True, "saved": True, "client_op_id": client_op_id or None}
    _record_client_op(
        user,
        client_op_id=client_op_id,
        op_type="save_action_eval",
        path=request.path,
        response_body=body,
        exercise_id=getattr(ex, "id", None),
    )
    return jsonify(body)


@bp.post("/action-eval/<int:slot>/approve")
@_require_judge_json
def tablet_action_eval_approve(user: User, slot: int):
    from app.evaluation_workflow import apply_judge_approve, eval_judge_can_edit
    from app.views import (
        _judge_planner_flow_action_bundle_row,
        _planner_bundle_eval_canonical_saved,
    )

    data = request.get_json(silent=True) or {}
    client_op_id = _client_op_id_from_request(data)
    replay = _idempotent_response(user, client_op_id)
    if replay is not None:
        return replay

    ex = _exercise_for(user)
    pair = _judge_planner_flow_action_bundle_row(g.db, user, ex, slot)
    if pair is None or ex is None:
        return _json_error("القائمة غير موجودة", 404)
    _, action_row = pair
    saved = _planner_bundle_eval_canonical_saved(g.db, ex.id, action_row.id)
    if saved is None:
        return _json_error("احفظ النتائج قبل الاعتماد", 400)
    if not eval_judge_can_edit(saved):
        # إن كانت معتمدة مسبقاً لنفس المحكم — نجاح Idempotent بدون خطأ
        if getattr(saved, "is_approved", False):
            body = {"ok": True, "approved": True, "already_approved": True}
            _record_client_op(
                user,
                client_op_id=client_op_id,
                op_type="approve_action_eval",
                path=request.path,
                response_body=body,
                exercise_id=getattr(ex, "id", None),
            )
            return jsonify(body)
        return _json_error("لا يمكن اعتماد هذه القائمة حالياً", 403)
    apply_judge_approve(saved, getattr(user, "id", None))
    g.db.commit()
    body = {"ok": True, "approved": True, "client_op_id": client_op_id or None}
    _record_client_op(
        user,
        client_op_id=client_op_id,
        op_type="approve_action_eval",
        path=request.path,
        response_body=body,
        exercise_id=getattr(ex, "id", None),
    )
    return jsonify(body)


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
                "label": (wf.get("eval_workflow_label") or wf.get("workflow_label") or ""),
                "reopened": bool(
                    wf.get("saved_reopened_for_judge") or wf.get("eval_reopened")
                ),
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

    data = request.get_json(silent=True) or {}
    client_op_id = _client_op_id_from_request(data)
    replay = _idempotent_response(user, client_op_id)
    if replay is not None:
        return replay

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
    payload = data.get("payload") if isinstance(data.get("payload"), dict) else data
    raw = json.dumps(payload, ensure_ascii=False)
    try:
        _evaluation_commit_payload_save(
            g.db, user=user, item=item, current_exercise=ex, raw=raw
        )
    except Exception as exc:
        return _json_error(str(exc) or "فشل الحفظ", 400)
    body = {"ok": True, "saved": True, "client_op_id": client_op_id or None}
    _record_client_op(
        user,
        client_op_id=client_op_id,
        op_type="save_evaluation_list",
        path=request.path,
        response_body=body,
        exercise_id=getattr(ex, "id", None),
    )
    return jsonify(body)


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

    data = request.get_json(silent=True) or {}
    client_op_id = _client_op_id_from_request(data)
    replay = _idempotent_response(user, client_op_id)
    if replay is not None:
        return replay

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
        if getattr(saved, "is_approved", False):
            body = {"ok": True, "approved": True, "already_approved": True}
            _record_client_op(
                user,
                client_op_id=client_op_id,
                op_type="approve_evaluation_list",
                path=request.path,
                response_body=body,
                exercise_id=getattr(ex, "id", None),
            )
            return jsonify(body)
        return _json_error("لا يمكن اعتماد هذه القائمة حالياً", 403)
    apply_judge_approve(saved, getattr(user, "id", None))
    g.db.commit()
    body = {"ok": True, "approved": True, "client_op_id": client_op_id or None}
    _record_client_op(
        user,
        client_op_id=client_op_id,
        op_type="approve_evaluation_list",
        path=request.path,
        response_body=body,
        exercise_id=getattr(ex, "id", None),
    )
    return jsonify(body)


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
        "menu": list(_TABLET_MAIN_MENU),
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
            "polarity_notes": _polarity_notes_payload(user, ex),
            "cached_at": datetime.utcnow().isoformat() + "Z",
        }
    )


@bp.post("/media/criterion")
@_require_judge_json
def tablet_media_upload(user: User):
    """رفع صورة/فيديو لعنصر تقييم — يغلف مسار النظام الحالي مع Idempotency."""
    from app.models.domain import EvaluationCriterionMedia
    from app.views import eval_criterion_media_upload

    client_op_id = _client_op_id_from_request()
    replay = _idempotent_response(user, client_op_id)
    if replay is not None:
        return replay

    if client_op_id:
        existing_media = (
            g.db.query(EvaluationCriterionMedia)
            .filter(
                EvaluationCriterionMedia.uploaded_by_id == int(user.id),
                EvaluationCriterionMedia.client_op_id == client_op_id,
            )
            .first()
        )
        if existing_media is not None:
            body = {
                "ok": True,
                "id": int(existing_media.id),
                "idempotent_replay": True,
                "client_op_id": client_op_id,
            }
            _record_client_op(
                user,
                client_op_id=client_op_id,
                op_type="media_upload",
                path=request.path,
                response_body=body,
                exercise_id=getattr(existing_media, "exercise_id", None),
            )
            return jsonify(body)

    resp = eval_criterion_media_upload()
    # بعد الرفع الناجح: اربط client_op_id إن أمكن
    if client_op_id:
        try:
            status = getattr(resp, "status_code", None)
            if status is None and isinstance(resp, tuple):
                status = resp[1] if len(resp) > 1 else 200
                payload = resp[0]
            else:
                payload = resp
            if int(status or 200) < 300:
                # أحدث وسائط رفعها هذا المستخدم
                row = (
                    g.db.query(EvaluationCriterionMedia)
                    .filter(EvaluationCriterionMedia.uploaded_by_id == int(user.id))
                    .order_by(EvaluationCriterionMedia.id.desc())
                    .first()
                )
                if row is not None and not (row.client_op_id or "").strip():
                    row.client_op_id = client_op_id
                    g.db.commit()
                body = {"ok": True, "client_op_id": client_op_id}
                if hasattr(payload, "get_json"):
                    try:
                        body = payload.get_json(silent=True) or body
                    except Exception:
                        pass
                elif isinstance(payload, dict):
                    body = payload
                body["client_op_id"] = client_op_id
                _record_client_op(
                    user,
                    client_op_id=client_op_id,
                    op_type="media_upload",
                    path=request.path,
                    response_body=body if isinstance(body, dict) else {"ok": True},
                    exercise_id=getattr(row, "exercise_id", None) if row else None,
                )
        except Exception:
            pass
    return resp


@bp.post("/media/upload/init")
@_require_judge_json
def tablet_media_upload_init(user: User):
    from app.tablet_media_resumable import init_upload

    body, status = init_upload(user, g.db)
    return jsonify(body), status


@bp.post("/media/upload/chunk")
@_require_judge_json
def tablet_media_upload_chunk(user: User):
    from app.tablet_media_resumable import upload_chunk

    body, status = upload_chunk(user)
    return jsonify(body), status


@bp.get("/media/upload/status")
@_require_judge_json
def tablet_media_upload_status(user: User):
    from app.tablet_media_resumable import upload_status

    body, status = upload_status(user)
    return jsonify(body), status


@bp.post("/media/upload/complete")
@_require_judge_json
def tablet_media_upload_complete(user: User):
    from app.tablet_media_resumable import complete_upload

    body, status = complete_upload(user, g.db)
    if status < 300 and body.get("ok") and body.get("client_uuid"):
        try:
            _record_client_op(
                user,
                client_op_id=str(body["client_uuid"]),
                op_type="media_upload",
                path=request.path,
                response_body=body,
                exercise_id=None,
            )
        except Exception:
            pass
    return jsonify(body), status


@bp.get("/library")
@_require_judge_json
def tablet_library(user: User):
    """مكتبة النظام — قراءة فقط (نفس تبويبات/شجرة صفحة المكتبة)."""
    from app.library_tree import LIBRARY_TAB_SPECS, LIBRARY_TREE_KINDS, build_tree_payload

    trees = {kind: build_tree_payload(g.db, kind) for kind in LIBRARY_TREE_KINDS}
    tabs = [
        {"tab_id": tab_id, "kind": kind, "title": title}
        for tab_id, kind, title in LIBRARY_TAB_SPECS
    ]
    return jsonify({"ok": True, "tabs": tabs, "trees": trees, "readonly": True})


@bp.get("/library/nodes/<int:node_id>/file")
@_require_judge_json
def tablet_library_file(user: User, node_id: int):
    """تنزيل/عرض ملف من المكتبة (جلسة التابلت)."""
    from flask import send_file

    from app.library_tree import is_library_tree_kind, node_file_abspath
    from app.models.domain import InformationBankTreeNode
    from app.views import _mimetype_info_bank_event_flow

    row = g.db.get(InformationBankTreeNode, node_id)
    if row is None or row.is_folder or not is_library_tree_kind(row.kind):
        return _json_error("الملف غير موجود", 404)
    if not (row.file_relpath or "").strip():
        return _json_error("الملف غير موجود", 404)
    path = node_file_abspath(row.kind, row.file_relpath)
    if path is None:
        return _json_error("الملف غير موجود على القرص", 404)
    low = path.name.lower()
    if low.endswith((".xlsx", ".xlsm")):
        mt = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    elif low.endswith(".docx"):
        mt = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    elif low.endswith(".doc"):
        mt = "application/msword"
    else:
        try:
            mt = _mimetype_info_bank_event_flow(path)
        except Exception:
            mt = "application/octet-stream"
    return send_file(path, mimetype=mt, as_attachment=False, download_name=path.name)


@bp.get("/notifications")
@_require_judge_json
def tablet_notifications(user: User):
    """سجل الإشعارات — نفس نطاق صفحة النظام، مع تعليم مقروء."""
    from sqlalchemy import desc

    from app.models.domain import ExerciseNotification
    from app.views import _notifications_scope_exercise

    if not can_view_notifications_log(user):
        return _json_error("غير مصرح", 403)
    ex = _notifications_scope_exercise(g.db, user)
    rows: list = []
    if ex is not None:
        rows = (
            g.db.query(ExerciseNotification)
            .filter(
                ExerciseNotification.user_id == int(user.id),
                ExerciseNotification.exercise_id == int(ex.id),
            )
            .order_by(desc(ExerciseNotification.created_at), desc(ExerciseNotification.id))
            .limit(500)
            .all()
        )

    def _type_label(t: str) -> str:
        return {
            "message": "رسالة",
            "meeting": "اجتماع",
            "document": "وثيقة / ملف",
            "task": "مهمة",
            "system": "نظام",
        }.get((t or "").strip(), "نظام")

    def _prio_label(p: str) -> str:
        return {
            "urgent": "عاجل",
            "important": "مهم",
        }.get((p or "").strip(), "عادي")

    items = []
    for n in rows:
        items.append(
            {
                "id": int(n.id),
                "type": (n.type or "").strip() or "system",
                "type_label": _type_label(n.type or ""),
                "title": (n.title or "").strip(),
                "body": (n.body or "").strip(),
                "priority": (n.priority or "").strip() or "normal",
                "priority_label": _prio_label(n.priority or ""),
                "created_at": n.created_at.strftime("%Y-%m-%d %H:%M") if n.created_at else "",
                "is_read": bool(n.is_read),
                "action_url": (n.action_url or "").strip(),
            }
        )
    return jsonify(
        {
            "ok": True,
            "has_exercise": ex is not None,
            "exercise_id": int(ex.id) if ex else None,
            "notifications": items,
            "unread_count": sum(1 for i in items if not i["is_read"]),
        }
    )


@bp.post("/notifications/<int:nid>/read")
@_require_judge_json
def tablet_notification_read(user: User, nid: int):
    from app.models.domain import ExerciseNotification
    from app.views import _notifications_scope_exercise

    if not can_view_notifications_log(user):
        return _json_error("غير مصرح", 403)
    ex = _notifications_scope_exercise(g.db, user)
    if ex is None:
        return _json_error("لا يوجد تمرين", 400)
    row = g.db.get(ExerciseNotification, nid)
    if (
        row
        and int(row.user_id) == int(user.id)
        and int(row.exercise_id) == int(ex.id)
    ):
        row.is_read = True
        g.db.add(row)
        g.db.commit()
        return jsonify({"ok": True, "id": int(nid), "is_read": True})
    return _json_error("الإشعار غير موجود", 404)


@bp.post("/notifications/read-all")
@_require_judge_json
def tablet_notifications_read_all(user: User):
    from app.models.domain import ExerciseNotification
    from app.views import _notifications_scope_exercise

    if not can_view_notifications_log(user):
        return _json_error("غير مصرح", 403)
    ex = _notifications_scope_exercise(g.db, user)
    if ex is None:
        return jsonify({"ok": True, "updated": 0})
    q = g.db.query(ExerciseNotification).filter(
        ExerciseNotification.user_id == int(user.id),
        ExerciseNotification.exercise_id == int(ex.id),
        ExerciseNotification.is_read.is_(False),
    )
    updated = 0
    for row in q.all():
        row.is_read = True
        g.db.add(row)
        updated += 1
    g.db.commit()
    return jsonify({"ok": True, "updated": updated})


@bp.post("/notifications/sync-event")
@_require_judge_json
def tablet_notifications_sync_event(user: User):
    """يسجّل تنبيهاً في سجل الإشعارات بعد مزامنة/تحديث ناجح من التابلت."""
    from app.notifications_service import notify_tablet_sync_event
    from app.views import _notifications_scope_exercise

    if not can_view_notifications_log(user):
        return _json_error("غير مصرح", 403)
    ex = _notifications_scope_exercise(g.db, user)
    if ex is None:
        return _json_error("لا يوجد تمرين", 400)
    data = request.get_json(silent=True) or {}
    kind = (data.get("kind") or "sync").strip().lower()
    detail = (data.get("detail") or "").strip()
    notify_tablet_sync_event(
        g.db,
        exercise_id=int(ex.id),
        user_id=int(user.id),
        kind=kind,
        detail=detail,
    )
    g.db.commit()
    # أعِد العدد غير المقروء فوراً للشارة
    from sqlalchemy import func

    from app.models.domain import ExerciseNotification

    unread = (
        g.db.query(func.count(ExerciseNotification.id))
        .filter(
            ExerciseNotification.user_id == int(user.id),
            ExerciseNotification.exercise_id == int(ex.id),
            ExerciseNotification.is_read.is_(False),
        )
        .scalar()
        or 0
    )
    return jsonify({"ok": True, "unread_count": int(unread)})


@bp.get("/exercise-details")
@_require_judge_json
def tablet_exercise_details(user: User):
    """معلومات التمرين — قراءة فقط بنفس أقسام صفحة النظام."""
    from sqlalchemy.orm import joinedload

    from app.exercise_text_format import split_idea_paragraphs
    from app.views import _EXERCISE_WORKSPACE_TABS, _exercise_type_level_display_text

    ex = _exercise_for(user)
    if ex is None:
        return _json_error("لا يوجد تمرين حالي", 404)
    ex = (
        g.db.query(Exercise)
        .options(joinedload(Exercise.objectives))
        .filter(Exercise.id == int(ex.id))
        .first()
    )
    if ex is None:
        return _json_error("لا يوجد تمرين حالي", 404)

    objectives = [
        {
            "id": int(o.id),
            "text": (o.text or "").strip(),
            "sort_order": int(o.sort_order or 0),
        }
        for o in sorted(
            ex.objectives or [], key=lambda x: (int(x.sort_order or 0), int(x.id))
        )
        if (o.text or "").strip()
    ]
    period = ""
    if ex.planned_start or ex.planned_end:
        ps = ex.planned_start.strftime("%d-%m-%Y") if ex.planned_start else "—"
        pe = ex.planned_end.strftime("%d-%m-%Y") if ex.planned_end else "—"
        period = f"من {ps} إلى {pe}"

    return jsonify(
        {
            "ok": True,
            "readonly": True,
            "tabs": [{"key": k, "label": lab} for k, lab in _EXERCISE_WORKSPACE_TABS],
            "exercise": {
                "id": int(ex.id),
                "name": (ex.title or "").strip(),
                "code": (ex.code or "").strip(),
                "trained_unit": (ex.trained_unit or "").strip(),
                "location": (ex.location_label or "").strip(),
                "type_label": (ex.exercise_type or "").strip(),
                "level_label": (ex.exercise_level or "").strip(),
                "period_label": period or _period_label(ex),
                "mission_label": (ex.mission_label or "").strip(),
                "exercise_purpose": (getattr(ex, "exercise_purpose", None) or "").strip(),
                "exercise_participants": (
                    getattr(ex, "exercise_participants", None) or ""
                ).strip(),
                "exercise_type_level_text": _exercise_type_level_display_text(ex),
                "general_idea_paragraphs": split_idea_paragraphs(
                    getattr(ex, "general_idea_text", None) or ""
                ),
                "specific_idea_paragraphs": split_idea_paragraphs(
                    getattr(ex, "specific_idea_text", None) or ""
                ),
                "objectives": objectives,
                "has_map": bool((getattr(ex, "map_image_relpath", None) or "").strip()),
                "has_program": bool(
                    (getattr(ex, "program_table_json", None) or "").strip()
                ),
            },
        }
    )


def _can_device_package_sync(user: User) -> bool:
    """تهيئة جهاز التابلت: إدارة / تخطيط / سيطرة / كبير محكمين."""
    return (
        is_system_admin(user)
        or can_plan_exercises(user)
        or can_access_control_hub(user)
        or can_access_chief_judge_hub(user)
    )


def _require_device_setup_user():
    user = get_current_user_optional()
    if user is None:
        return None, _json_error("يلزم تسجيل الدخول", 401)
    if not _can_device_package_sync(user):
        return None, _json_error("لا صلاحية لتهيئة جهاز المحكمين", 403)
    if not session.get("device_setup"):
        return None, _json_error("جلسة تهيئة الجهاز غير نشطة", 403)
    return user, None


@bp.post("/device/setup-login")
def tablet_device_setup_login():
    """دخول فني لتهيئة الجهاز وتنزيل حزمة التمرين (ليس Local Admin المحلي)."""
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    if not username or not password:
        return _json_error("أدخل اسم المستخدم وكلمة المرور", 400)
    user = (
        g.db.query(User)
        .filter(User.username == username, User.is_active == True)  # noqa: E712
        .first()
    )
    if user is None or not verify_password(password, user.password_hash or ""):
        return _json_error("بيانات الدخول غير صحيحة", 401)
    if not _can_device_package_sync(user):
        return _json_error("هذا الحساب لا يملك صلاحية تهيئة أجهزة المحكمين", 403)
    session.clear()
    session["user_id"] = int(user.id)
    session["device_setup"] = True
    session.permanent = True
    ex = _exercise_for(user)
    return jsonify(
        {
            "ok": True,
            "device_setup": True,
            "user": {
                "id": int(user.id),
                "username": user.username,
                "full_name": user.full_name or "",
                "role_key": user.role_key or "",
            },
            "exercise": None
            if ex is None
            else {
                "id": int(ex.id),
                "name": (ex.title or "").strip(),
                "code": (ex.code or "").strip(),
            },
        }
    )


@bp.get("/device/package")
def tablet_device_package():
    """حزمة تمرين كاملة للعمل Offline على التابلت — معزولة لكل محكم."""
    from app.models.domain import JudgeTraineeAssignment
    from app.views import (
        _build_incomplete_evaluations_report,
        _collect_all_eval_status_rows_flat,
    )

    setup_user, err = _require_device_setup_user()
    if err is not None:
        return err
    assert setup_user is not None

    ex = _exercise_for(setup_user)
    if ex is None:
        return _json_error("لا يوجد تمرين نشط", 404)

    objectives = (
        g.db.query(ExerciseObjective)
        .filter(ExerciseObjective.exercise_id == int(ex.id))
        .order_by(ExerciseObjective.sort_order, ExerciseObjective.id)
        .all()
    )
    objectives_out = [
        {
            "id": int(r.id),
            "sort_order": int(r.sort_order or 0),
            "text": r.text or "",
        }
        for r in objectives
    ]

    judge_users = (
        g.db.query(User)
        .filter(User.is_active == True)  # noqa: E712
        .all()
    )
    judges_out: list[dict] = []
    for ju in judge_users:
        if not can_access_judge_hub(ju):
            continue
        if not (is_judge(ju) or can_access_chief_judge_hub(ju)):
            continue
        me = _serialize_user_bundle(ju, ex)
        mil = ""
        try:
            asg = (
                g.db.query(JudgeTraineeAssignment)
                .filter(
                    JudgeTraineeAssignment.exercise_id == int(ex.id),
                    JudgeTraineeAssignment.judge_user_id == int(ju.id),
                )
                .first()
            )
            if asg is not None:
                mil = (asg.judge_military_number or "").strip()
        except Exception:
            mil = ""
        if not mil:
            mil = (ju.username or "").strip()

        incomplete = _build_incomplete_evaluations_report(g.db, ju, role="judge")
        incomplete_rows = [
            _safe_row(r) for r in (incomplete.get("incomplete_rows") or [])
        ]
        incomplete_count = int(incomplete.get("incomplete_count") or 0)
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
            "menu": list(_TABLET_MAIN_MENU),
        }
        eval_lists = {
            "ok": True,
            "unit_key": uk or "",
            "phase_key": "",
            "lists": [_safe_row(r) for r in all_rows[:200]],
            "rows": [_safe_row(r) for r in all_rows[:200]],
            "unit_levels": [],
            "phase_tabs": [],
        }
        judges_out.append(
            {
                "user_id": int(ju.id),
                "username": (ju.username or "").strip(),
                "military_number": mil,
                "local_password_seed": mil or (ju.username or "").strip(),
                "session": me,
                "home": home_payload,
                "objectives": objectives_out,
                "incomplete_tasks": incomplete_rows,
                "evaluation_lists": eval_lists,
                "polarity_notes": _polarity_notes_payload(ju, ex),
            }
        )

    return jsonify(
        {
            "ok": True,
            "cached_at": datetime.utcnow().isoformat() + "Z",
            "exercise": {
                "id": int(ex.id),
                "name": (ex.title or "").strip(),
                "code": (ex.code or "").strip(),
                "location": (ex.location_label or "").strip(),
                "period_label": _period_label(ex),
            },
            "objectives": objectives_out,
            "judges": judges_out,
            "judge_count": len(judges_out),
        }
    )


def _polarity_notes_payload(user: User, ex: Exercise | None) -> dict:
    """قائمة الإيجابيات/السلبيات العامة للوحدة — مطابقة لصفحة الويب."""
    from app.judge_polarity_notes import list_general_notes_for_scope

    if ex is None:
        return {
            "ok": True,
            "exercise_id": 0,
            "unit_key": "",
            "unit_label": "",
            "notes": [],
            "notes_pos_count": 0,
            "notes_neg_count": 0,
        }
    uk = (_unit_key_for(user, ex) or "").strip()
    ulabel = label_for_unit_level_key(uk, db=g.db) if uk else ""
    pos = (
        list_general_notes_for_scope(
            g.db,
            user,
            exercise_id=int(ex.id),
            unit_level_key=uk,
            polarity="positive",
        )
        if uk
        else []
    )
    neg = (
        list_general_notes_for_scope(
            g.db,
            user,
            exercise_id=int(ex.id),
            unit_level_key=uk,
            polarity="negative",
        )
        if uk
        else []
    )
    return {
        "ok": True,
        "exercise_id": int(ex.id),
        "unit_key": uk,
        "unit_label": (ulabel or uk),
        "notes": list(pos) + list(neg),
        "notes_pos_count": len(pos),
        "notes_neg_count": len(neg),
    }


@bp.get("/me/updates")
@_require_judge_json
def tablet_me_updates(user: User):
    """تحديثات شخصية للمحكم الحالي فقط (Update My Data)."""
    return tablet_bootstrap(user)


@bp.get("/polarity-notes")
@_require_judge_json
def tablet_polarity_notes_list(user: User):
    ex = _exercise_for(user)
    if ex is None:
        return _json_error("لا يوجد تمرين نشط", 404)
    return jsonify(_polarity_notes_payload(user, ex))


@bp.post("/polarity-notes/bulk")
@_require_judge_json
def tablet_polarity_notes_bulk(user: User):
    """استبدال قائمة الإيجابيات أو السلبيات للوحدة — مثل حفظ صفحة الويب."""
    from app.judge_polarity_notes import replace_general_notes_for_scope

    ex = _exercise_for(user)
    if ex is None:
        return _json_error("لا يوجد تمرين نشط", 404)
    data = request.get_json(silent=True) or {}
    client_op_id = _client_op_id_from_request(data)
    replay = _idempotent_response(user, client_op_id)
    if replay is not None:
        return replay

    uk = (data.get("unit_level_key") or _unit_key_for(user, ex) or "").strip()
    assigned = (_unit_key_for(user, ex) or "").strip()
    # المحكم الفردي يُقيَّد بوحدته المسندة
    if assigned and uk and uk != assigned and is_judge(user) and not is_system_admin(user):
        if not can_access_chief_judge_hub(user):
            uk = assigned
    if not uk:
        return _json_error("لا توجد وحدة مخصّصة", 400)

    polarity = (data.get("polarity") or "positive").strip().lower()
    raw_bodies = data.get("bodies")
    if not isinstance(raw_bodies, list):
        raw_bodies = data.get("pn_items") or []
    if not isinstance(raw_bodies, list):
        raw_bodies = []
    bodies = [str(x) for x in raw_bodies]

    body, status = replace_general_notes_for_scope(
        g.db,
        user,
        exercise_id=int(ex.id),
        unit_level_key=uk,
        polarity=polarity,
        bodies=bodies,
        judge_label=_judge_display_name(user, ex),
    )
    if status >= 400:
        g.db.rollback()
        return jsonify(body), status
    # أعد الحمولة الكاملة للوحدة بعد الاستبدال
    payload = _polarity_notes_payload(user, ex)
    payload["replaced_polarity"] = polarity
    payload["replaced_count"] = int(body.get("count") or 0)
    g.db.commit()
    if client_op_id:
        _record_client_op(
            user,
            client_op_id=client_op_id,
            op_type="polarity_notes_bulk",
            path=request.path,
            response_body=payload,
            exercise_id=int(ex.id),
        )
    return jsonify(payload), 200


@bp.post("/polarity-notes")
@_require_judge_json
def tablet_polarity_notes_save(user: User):
    from app.judge_polarity_notes import upsert_note

    ex = _exercise_for(user)
    if ex is None:
        return _json_error("لا يوجد تمرين نشط", 404)
    data = request.get_json(silent=True) or {}
    client_op_id = _client_op_id_from_request(data)
    if client_op_id and not data.get("client_uuid"):
        data["client_uuid"] = client_op_id
    replay = _idempotent_response(user, client_op_id)
    if replay is not None:
        return replay
    # السجلات العامة المشتركة: فرض source_kind=general ووحدة المحكم
    if (data.get("source_kind") or "general").strip().lower() == "general":
        data["source_kind"] = "general"
    body, status = upsert_note(
        g.db,
        user,
        exercise_id=int(ex.id),
        unit_level_key=_unit_key_for(user, ex) or "",
        judge_label=_judge_display_name(user, ex),
        data=data,
    )
    if status >= 400:
        g.db.rollback()
        return jsonify(body), status
    g.db.commit()
    if client_op_id:
        _record_client_op(
            user,
            client_op_id=client_op_id,
            op_type="polarity_note_save",
            path=request.path,
            response_body=body,
            exercise_id=int(ex.id),
        )
    return jsonify(body), status


@bp.delete("/polarity-notes/<int:note_id>")
@_require_judge_json
def tablet_polarity_notes_delete(user: User, note_id: int):
    from app.judge_polarity_notes import delete_note
    from app.models import JudgePolarityNote

    # السجلات العامة المشتركة: أي محكم لنفس الوحدة يمكنه الحذف (مثل الاستبدال الجماعي)
    row = g.db.get(JudgePolarityNote, int(note_id))
    if row is None:
        return jsonify({"ok": False, "error": "not_found"}), 404
    ex = _exercise_for(user)
    uk = (_unit_key_for(user, ex) or "").strip() if ex else ""
    if (
        (row.source_kind or "") == "general"
        and ex is not None
        and int(row.exercise_id) == int(ex.id)
        and (row.unit_level_key or "").strip() == uk
        and uk
    ):
        g.db.delete(row)
        g.db.commit()
        return jsonify({"ok": True, "deleted": True}), 200

    body, status = delete_note(g.db, user, note_id, "")
    if status >= 400:
        g.db.rollback()
        return jsonify(body), status
    g.db.commit()
    return jsonify(body), status
