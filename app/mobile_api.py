"""JSON API للتطبيق المحمّل (تابلت المحكمين)."""
from __future__ import annotations

import json
from datetime import datetime

from flask import Blueprint, g, jsonify, request, session

from app.auth import get_current_user_optional, verify_password
from app.evaluation_workflow import (
    apply_chief_approve,
    apply_chief_reopen,
    apply_judge_approve,
    build_evaluation_list_row,
    eval_chief_can_approve,
    eval_chief_can_reopen,
    eval_judge_can_approve,
    evaluation_unit_home_phase_tabs,
    eval_workflow_label_ar,
    filter_evaluation_items_by_phase,
)
from app.models import (
    EvaluationListPdfItem,
    EvaluationListSavedResult,
    ExerciseNotification,
    ExerciseRosterKind,
    ExerciseRosterRow,
    RoleKey,
    User,
)
from app.permissions import (
    can_access_chief_judge_hub,
    can_access_judge_hub,
    can_approve_evaluation_results,
    can_chief_approve_evaluation_results,
    can_chief_reopen_evaluation_for_judge,
    can_save_evaluation_results,
    can_view_notifications_log,
    is_chief_judge,
    is_judge,
    is_system_admin,
)
from sqlalchemy import desc, func

mobile_bp = Blueprint("mobile_api", __name__, url_prefix="/api/mobile/v1")


@mobile_bp.route("/ping", methods=["GET"])
def mobile_ping():
    """فحص اتصال عام — لا يتطلب تسجيل دخول (لتطبيق التابلت)."""
    return jsonify({"ok": True, "service": "lf-judge-mobile"})


def _require_user():
    user = get_current_user_optional()
    if not user:
        return None, (jsonify({"ok": False, "error": "unauthorized"}), 401)
    return user, None


def _iso_dt(v) -> str:
    if v is None:
        return ""
    if isinstance(v, datetime):
        return v.isoformat()
    return str(v)


def _user_payload(db, user: User) -> dict:
    from app.views import (
        _current_workspace_exercise,
        _is_individual_judge_user,
        _judge_assigned_unit_key,
    )

    ex = _current_workspace_exercise(db, user)
    assigned = _judge_assigned_unit_key(db, user, ex)
    rk = (user.role_key or "").strip()
    if is_chief_judge(user):
        role_tier = "chief_judge"
    elif is_system_admin(user):
        role_tier = "admin"
    elif _is_individual_judge_user(user):
        role_tier = "individual_judge"
    else:
        role_tier = "lead_judge"
    return {
        "id": int(user.id),
        "username": (user.username or "").strip(),
        "full_name": (user.full_name or "").strip(),
        "role_key": rk,
        "role_tier": role_tier,
        "assigned_unit_key": assigned,
        "can_chief_hub": bool(can_access_chief_judge_hub(user)),
        "can_judge_hub": bool(can_access_judge_hub(user)),
        "exercise": None
        if ex is None
        else {
            "id": int(ex.id),
            "name": (getattr(ex, "title", "") or "").strip(),
            "code": (getattr(ex, "code", "") or "").strip(),
            "trained_unit": (getattr(ex, "trained_unit", "") or "").strip(),
            "exercise_type": (getattr(ex, "exercise_type", "") or "").strip(),
        },
    }


def _hub_items_json(db, user: User) -> dict:
    from app.views import (
        CHIEF_JUDGE_ONLY_HUB_ITEMS,
        _judge_hub_menu_items,
    )

    judge_src = _judge_hub_menu_items(user)
    judge_items = [
        {"slug": s, "title": t, "icon": ic}
        for s, t, ic in judge_src
    ]
    chief_items = []
    if can_access_chief_judge_hub(user):
        chief_items = [
            {"slug": s, "title": t, "icon": ic}
            for s, t, ic in CHIEF_JUDGE_ONLY_HUB_ITEMS
        ]
    return {"judge_items": judge_items, "chief_items": chief_items}


@mobile_bp.route("/auth/login", methods=["POST"])
def mobile_login():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    if not username or not password:
        return jsonify({"ok": False, "error": "missing_credentials"}), 400
    db = g.db
    u = (
        db.query(User)
        .filter(User.username == username, User.is_active == True)  # noqa: E712
        .first()
    )
    if not u or not verify_password(password, u.password_hash):
        return jsonify({"ok": False, "error": "invalid_credentials"}), 401
    rk = (u.role_key or "").strip()
    if rk not in (RoleKey.JUDGE.value, RoleKey.CHIEF_JUDGE.value) and not is_system_admin(u):
        return jsonify({"ok": False, "error": "judge_role_required"}), 403
    u.last_login = datetime.utcnow()
    db.add(u)
    db.commit()
    session["user_id"] = u.id
    return jsonify({"ok": True, "user": _user_payload(db, u)})


@mobile_bp.route("/auth/logout", methods=["POST"])
def mobile_logout():
    session.clear()
    return jsonify({"ok": True})


@mobile_bp.route("/session", methods=["GET"])
def mobile_session():
    user, err = _require_user()
    if err:
        return err
    return jsonify({"ok": True, "user": _user_payload(g.db, user)})


@mobile_bp.route("/judge/hub", methods=["GET"])
def mobile_judge_hub():
    user, err = _require_user()
    if err:
        return err
    if not can_access_judge_hub(user) and not can_access_chief_judge_hub(user):
        return jsonify({"ok": False, "error": "forbidden"}), 403
    return jsonify({"ok": True, **_hub_items_json(g.db, user)})


@mobile_bp.route("/judge/evaluation-lists", methods=["GET"])
def mobile_eval_lists_home():
    user, err = _require_user()
    if err:
        return err
    if not can_access_judge_hub(user):
        return jsonify({"ok": False, "error": "forbidden"}), 403
    from app.views import (
        _current_workspace_exercise,
        _ensure_judge_roster_synced,
        _evaluation_list_home_active_phase,
        _judge_evaluation_list_unit_levels,
    )

    db = g.db
    ex = _current_workspace_exercise(db, user)
    _ensure_judge_roster_synced(db, user, ex)
    units = _judge_evaluation_list_unit_levels(db, user, ex)
    phase_tabs = evaluation_unit_home_phase_tabs(db, ex, units)
    tabs_out = []
    for tab in phase_tabs:
        tabs_out.append(
            {
                "phase_key": tab.get("phase_key") or "",
                "phase_label": tab.get("phase_label") or "",
                "totals": tab.get("totals") or {"total": 0, "not_done": 0},
                "unit_rows": [
                    {
                        "key": r.get("key") or "",
                        "label": r.get("label") or "",
                        "total_count": int(r.get("total_count") or 0),
                        "not_done_count": int(r.get("not_done_count") or 0),
                    }
                    for r in tab.get("unit_rows") or []
                ],
            }
        )
    return jsonify(
        {
            "ok": True,
            "has_exercise": ex is not None,
            "active_phase_key": _evaluation_list_home_active_phase(phase_tabs),
            "phase_tabs": tabs_out,
        }
    )


@mobile_bp.route("/judge/evaluation-lists/<unit_key>", methods=["GET"])
def mobile_eval_lists_unit(unit_key: str):
    user, err = _require_user()
    if err:
        return err
    if not can_access_judge_hub(user):
        return jsonify({"ok": False, "error": "forbidden"}), 403
    from app.views import (
        _current_workspace_exercise,
        _enforce_judge_unit_scope,
        _evaluation_canonical_map_for_items,
        _evaluation_list_phase_from_request,
        _evaluation_list_resolved_phase,
        _exercise_phase_order_expr,
        _require_unit_level_row,
        _unit_level_order_expr,
    )

    db = g.db
    unit = _require_unit_level_row(unit_key)
    ex = _current_workspace_exercise(db, user)
    if ex is None:
        return jsonify({"ok": False, "error": "no_exercise"}), 400
    _enforce_judge_unit_scope(db, user, ex, unit_key)
    phase_key = request.args.get("phase") or _evaluation_list_phase_from_request()
    items = (
        db.query(EvaluationListPdfItem)
        .filter(
            EvaluationListPdfItem.exercise_id == ex.id,
            EvaluationListPdfItem.unit_level_key == unit_key,
        )
        .order_by(
            _exercise_phase_order_expr(EvaluationListPdfItem.exercise_phase),
            EvaluationListPdfItem.sort_order,
            EvaluationListPdfItem.id,
        )
        .all()
    )
    items = filter_evaluation_items_by_phase(items, phase_key)
    item_ids = [int(it.id) for it in items]
    canonical = _evaluation_canonical_map_for_items(db, ex.id, item_ids)
    rows = []
    for it in items:
        s = canonical.get(int(it.id))
        row = build_evaluation_list_row(
            item=it,
            saved=s,
            exercise=ex,
            open_href="",
        )
        rows.append(
            {
                "item_id": row["item_id"],
                "title": row["item_title"],
                "updated_at": _iso_dt(row.get("dt")),
                "exercise_type": row.get("exercise_type") or "",
                "trained_unit": row.get("trained_unit") or "",
                "delivery_at": _iso_dt(row.get("delivery_dt")),
                "status_label": row.get("status_label") or "",
                "status_done": bool(row.get("status_done")),
                "grade_label": row.get("grade_label") or "",
                "dispatch_label": row.get("dispatch_label") or "",
                "workflow_label": eval_workflow_label_ar(s),
                "phase_key": _evaluation_list_resolved_phase(it),
            }
        )
    return jsonify(
        {
            "ok": True,
            "unit_key": unit_key,
            "unit_label": (unit.get("label") or unit_key).strip(),
            "phase_key": phase_key or "",
            "rows": rows,
        }
    )


@mobile_bp.route("/judge/evaluation-lists/<unit_key>/<int:item_id>", methods=["GET"])
def mobile_eval_detail(unit_key: str, item_id: int):
    user, err = _require_user()
    if err:
        return err
    if not can_access_judge_hub(user):
        return jsonify({"ok": False, "error": "forbidden"}), 403
    from app.views import (
        _current_workspace_exercise,
        _enforce_judge_unit_scope,
        _eval_list_viewer_ctx,
        _evaluation_canonical_saved_row,
        _evaluation_list_file_abspath,
        _evaluation_list_resolved_phase,
        _evaluation_sheet_view_context,
        _require_unit_level_row,
        _saved_payload_aligned_with_eval_rows,
    )

    db = g.db
    unit = _require_unit_level_row(unit_key)
    ex = _current_workspace_exercise(db, user)
    row = db.get(EvaluationListPdfItem, item_id)
    if (
        not row
        or row.unit_level_key != unit_key
        or ex is None
        or row.exercise_id != ex.id
    ):
        return jsonify({"ok": False, "error": "not_found"}), 404
    _enforce_judge_unit_scope(db, user, ex, unit_key)
    if not (row.pdf_relpath or "").strip():
        return jsonify({"ok": False, "error": "no_file"}), 404
    fspath = _evaluation_list_file_abspath(row.pdf_relpath)
    if fspath is None:
        return jsonify({"ok": False, "error": "file_missing"}), 404
    ev = _evaluation_sheet_view_context(fspath)
    canon = _evaluation_canonical_saved_row(db, ex.id, row.id)
    saved_payload = {}
    if canon and (canon.payload_json or "").strip():
        try:
            p = json.loads(canon.payload_json)
            saved_payload = p if isinstance(p, dict) else {}
        except Exception:
            saved_payload = {}
    saved_payload = _saved_payload_aligned_with_eval_rows(saved_payload, ev.get("eval_rows"))
    wf = _eval_list_viewer_ctx(user, canon)
    commander_name = "—"
    cr = (
        db.query(ExerciseRosterRow)
        .filter(
            ExerciseRosterRow.exercise_id == ex.id,
            ExerciseRosterRow.roster_kind == ExerciseRosterKind.TRAINEE.value,
            ExerciseRosterRow.unit_level_key == unit_key,
        )
        .order_by(ExerciseRosterRow.sort_order, ExerciseRosterRow.id)
        .first()
    )
    if cr is not None:
        commander_name = (cr.full_name or "").strip() or commander_name
    judge_name = (user.full_name or user.username or "").strip()
    return jsonify(
        {
            "ok": True,
            "unit_key": unit_key,
            "unit_label": (unit.get("label") or unit_key).strip(),
            "item_id": int(row.id),
            "item_title": (row.text or "تقييم").strip(),
            "phase_key": _evaluation_list_resolved_phase(row),
            "sheet_title": ev.get("sheet_title") or "",
            "eval_structured": bool(ev.get("eval_structured")),
            "eval_rows": ev.get("eval_rows") or [],
            "eval_input_mode": ev.get("eval_input_mode") or "scale5",
            "acquired_options": ev.get("acquired_options") or [],
            "saved_payload": saved_payload,
            "saved_updated_at": _iso_dt(getattr(canon, "updated_at", None) if canon else None),
            "commander_name": commander_name,
            "judge_name": judge_name,
            "workflow": {
                "label": eval_workflow_label_ar(canon),
                **wf,
            },
        }
    )


def _mobile_eval_save_impl(user: User, unit_key: str, item_id: int, raw: str) -> tuple[bool, str]:
    from app.views import (
        _current_workspace_exercise,
        _enforce_judge_unit_scope,
        _evaluation_commit_payload_save,
        _evaluation_save_payload_missing_row_notes,
        _require_unit_level_row,
    )

    if not can_save_evaluation_results(user):
        return False, "forbidden"
    db = g.db
    _require_unit_level_row(unit_key)
    item = db.get(EvaluationListPdfItem, item_id)
    ex = _current_workspace_exercise(db, user)
    if (
        not item
        or item.unit_level_key != unit_key
        or ex is None
        or item.exercise_id != ex.id
    ):
        return False, "not_found"
    _enforce_judge_unit_scope(db, user, ex, unit_key)
    if not raw:
        return False, "empty_payload"
    if len(raw) > 250_000:
        return False, "payload_too_large"
    if _evaluation_save_payload_missing_row_notes(raw):
        return False, "notes_required"
    try:
        _evaluation_commit_payload_save(
            db, user=user, item=item, current_exercise=ex, raw=raw
        )
    except Exception as exc:
        return False, str(exc)
    return True, ""


@mobile_bp.route("/judge/evaluation-lists/<unit_key>/<int:item_id>/save", methods=["POST"])
def mobile_eval_save(unit_key: str, item_id: int):
    user, err = _require_user()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    raw = (data.get("payload_json") or "").strip()
    if isinstance(data.get("payload"), dict):
        raw = json.dumps(data["payload"], ensure_ascii=False)
    ok, error = _mobile_eval_save_impl(user, unit_key, item_id, raw)
    if not ok:
        code = 403 if error == "forbidden" else 400
        if error == "not_found":
            code = 404
        return jsonify({"ok": False, "error": error}), code
    return jsonify({"ok": True})


@mobile_bp.route("/judge/evaluation-lists/<unit_key>/<int:item_id>/approve", methods=["POST"])
def mobile_eval_approve(unit_key: str, item_id: int):
    user, err = _require_user()
    if err:
        return err
    if not can_approve_evaluation_results(user):
        return jsonify({"ok": False, "error": "forbidden"}), 403
    from app.views import (
        _current_workspace_exercise,
        _enforce_judge_unit_scope,
        _evaluation_canonical_saved_row,
        _evaluation_payload_has_empty_acquired_for_approve,
        _evaluation_saved_allows_judge_approve,
        _parse_saved_eval_rows,
        _require_unit_level_row,
    )

    db = g.db
    _require_unit_level_row(unit_key)
    item = db.get(EvaluationListPdfItem, item_id)
    ex = _current_workspace_exercise(db, user)
    if (
        not item
        or item.unit_level_key != unit_key
        or ex is None
        or item.exercise_id != ex.id
    ):
        return jsonify({"ok": False, "error": "not_found"}), 404
    _enforce_judge_unit_scope(db, user, ex, unit_key)
    saved = _evaluation_canonical_saved_row(db, ex.id, item.id)
    if saved is None or not (saved.payload_json or "").strip():
        return jsonify({"ok": False, "error": "not_saved"}), 400
    if not eval_judge_can_approve(saved):
        return jsonify({"ok": False, "error": "cannot_approve"}), 400
    rows = _parse_saved_eval_rows(saved.payload_json)
    if _evaluation_payload_has_empty_acquired_for_approve(rows):
        return jsonify({"ok": False, "error": "incomplete_scores"}), 400
    if not _evaluation_saved_allows_judge_approve(saved):
        return jsonify({"ok": False, "error": "grade_blocked"}), 400
    apply_judge_approve(saved, getattr(user, "id", None))
    db.commit()
    return jsonify({"ok": True})


@mobile_bp.route(
    "/chief-judge/evaluation-lists/<unit_key>/<int:item_id>/chief-approve",
    methods=["POST"],
)
def mobile_chief_approve(unit_key: str, item_id: int):
    user, err = _require_user()
    if err:
        return err
    if not can_chief_approve_evaluation_results(user):
        return jsonify({"ok": False, "error": "forbidden"}), 403
    from app.views import (
        _current_workspace_exercise,
        _evaluation_canonical_saved_row,
        _require_unit_level_row,
    )

    db = g.db
    _require_unit_level_row(unit_key)
    item = db.get(EvaluationListPdfItem, item_id)
    ex = _current_workspace_exercise(db, user)
    if (
        not item
        or item.unit_level_key != unit_key
        or ex is None
        or item.exercise_id != ex.id
    ):
        return jsonify({"ok": False, "error": "not_found"}), 404
    saved = _evaluation_canonical_saved_row(db, ex.id, item.id)
    if saved is None or not eval_chief_can_approve(saved):
        return jsonify({"ok": False, "error": "cannot_approve"}), 400
    apply_chief_approve(saved, getattr(user, "id", None))
    db.commit()
    return jsonify({"ok": True})


@mobile_bp.route(
    "/chief-judge/evaluation-lists/<unit_key>/<int:item_id>/reopen",
    methods=["POST"],
)
def mobile_chief_reopen(unit_key: str, item_id: int):
    user, err = _require_user()
    if err:
        return err
    if not can_chief_reopen_evaluation_for_judge(user):
        return jsonify({"ok": False, "error": "forbidden"}), 403
    from app.views import (
        _current_workspace_exercise,
        _evaluation_canonical_saved_row,
        _require_unit_level_row,
    )
    from app.notifications_service import notify_evaluation_reopened_by_chief_judge
    from app.unit_levels_catalog import label_for_unit_level_key

    db = g.db
    unit = _require_unit_level_row(unit_key)
    item = db.get(EvaluationListPdfItem, item_id)
    ex = _current_workspace_exercise(db, user)
    if (
        not item
        or item.unit_level_key != unit_key
        or ex is None
        or item.exercise_id != ex.id
    ):
        return jsonify({"ok": False, "error": "not_found"}), 404
    saved = _evaluation_canonical_saved_row(db, ex.id, item.id)
    if saved is None or not eval_chief_can_reopen(saved):
        return jsonify({"ok": False, "error": "cannot_reopen"}), 400
    apply_chief_reopen(saved)
    unit_label = label_for_unit_level_key(unit_key) or unit.get("label") or unit_key
    item_title = (getattr(item, "text", None) or "قائمة التقييم").strip()
    notify_evaluation_reopened_by_chief_judge(
        db,
        exercise_id=int(ex.id),
        unit_key=unit_key,
        unit_label=unit_label,
        item_title=item_title,
        item_id=int(item.id),
        saved_by_user_id=getattr(saved, "saved_by_id", None),
        exclude_user_id=getattr(user, "id", None),
    )
    db.commit()
    return jsonify({"ok": True})


@mobile_bp.route("/judge/incomplete-tasks", methods=["GET"])
def mobile_incomplete_tasks():
    user, err = _require_user()
    if err:
        return err
    if not can_access_judge_hub(user):
        return jsonify({"ok": False, "error": "forbidden"}), 403
    from app.views import _build_incomplete_evaluations_report

    report = _build_incomplete_evaluations_report(g.db, user, role="judge")
    rows_out = []
    for r in report.get("incomplete_rows") or []:
        rows_out.append(
            {
                "kind": r.get("kind") or "",
                "title": r.get("title") or "",
                "unit_label": r.get("unit_label") or "",
                "unit_key": r.get("unit_key") or "",
                "item_id": r.get("item_id"),
                "phase_label": r.get("phase_label") or "",
                "started_at": _iso_dt(r.get("started_at")),
                "status_label": r.get("status_label") or "",
            }
        )
    return jsonify(
        {
            "ok": True,
            "has_exercise": bool(report.get("has_exercise")),
            "count": int(report.get("incomplete_count") or 0),
            "rows": rows_out,
        }
    )


@mobile_bp.route("/notifications", methods=["GET"])
def mobile_notifications():
    user, err = _require_user()
    if err:
        return err
    if not can_view_notifications_log(user):
        return jsonify({"ok": False, "error": "forbidden"}), 403
    from app.views import _notifications_scope_exercise

    db = g.db
    ex = _notifications_scope_exercise(db, user)
    if ex is None:
        return jsonify({"ok": True, "rows": [], "unread_count": 0})
    rows = (
        db.query(ExerciseNotification)
        .filter(
            ExerciseNotification.user_id == int(user.id),
            ExerciseNotification.exercise_id == int(ex.id),
        )
        .order_by(desc(ExerciseNotification.created_at), desc(ExerciseNotification.id))
        .limit(100)
        .all()
    )
    unread = (
        db.query(func.count(ExerciseNotification.id))
        .filter(
            ExerciseNotification.user_id == int(user.id),
            ExerciseNotification.exercise_id == int(ex.id),
            ExerciseNotification.is_read == False,  # noqa: E712
        )
        .scalar()
        or 0
    )
    return jsonify(
        {
            "ok": True,
            "unread_count": int(unread),
            "rows": [
                {
                    "id": int(r.id),
                    "type": r.type or "",
                    "title": r.title or "",
                    "body": (r.body or "")[:2000],
                    "priority": r.priority or "normal",
                    "is_read": bool(r.is_read),
                    "created_at": _iso_dt(r.created_at),
                    "action_url": r.action_url or "",
                }
                for r in rows
            ],
        }
    )


@mobile_bp.route("/notifications/<int:nid>/read", methods=["POST"])
def mobile_notification_read(nid: int):
    user, err = _require_user()
    if err:
        return err
    from app.views import _notifications_scope_exercise

    db = g.db
    ex = _notifications_scope_exercise(db, user)
    if ex is None:
        return jsonify({"ok": False, "error": "no_exercise"}), 400
    row = db.get(ExerciseNotification, nid)
    if (
        not row
        or int(row.user_id) != int(user.id)
        or int(row.exercise_id) != int(ex.id)
    ):
        return jsonify({"ok": False, "error": "not_found"}), 404
    if not row.is_read:
        row.is_read = True
        db.add(row)
        db.commit()
    return jsonify({"ok": True})


def _sync_process_operation(user: User, op: dict) -> tuple[bool, str]:
    op_type = (op.get("type") or "").strip()
    unit_key = (op.get("unit_key") or "").strip()
    item_id = int(op.get("item_id") or 0)
    if not unit_key or not item_id:
        return False, "missing_target"
    if op_type == "eval_save":
        payload = (op.get("payload_json") or "").strip()
        if not payload and isinstance(op.get("payload"), dict):
            payload = json.dumps(op["payload"], ensure_ascii=False)
        return _mobile_eval_save_impl(user, unit_key, item_id, payload)
    if op_type == "eval_approve":
        resp = mobile_eval_approve(unit_key, item_id)
    elif op_type == "chief_approve":
        resp = mobile_chief_approve(unit_key, item_id)
    elif op_type == "chief_reopen":
        resp = mobile_chief_reopen(unit_key, item_id)
    else:
        return False, "unknown_type"
    if isinstance(resp, tuple):
        body, code = resp[0].get_json(), resp[1]
    else:
        body, code = resp.get_json(), resp.status_code
    if code >= 400 or not body.get("ok"):
        return False, body.get("error") or "failed"
    return True, ""


@mobile_bp.route("/sync/push", methods=["POST"])
def mobile_sync_push():
    """رفع عمليات محفوظة محلياً (حفظ/اعتماد) دفعة واحدة."""
    user, err = _require_user()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    ops = data.get("operations") or []
    if not isinstance(ops, list):
        return jsonify({"ok": False, "error": "invalid_operations"}), 400
    results = []
    for op in ops:
        if not isinstance(op, dict):
            results.append({"client_id": "", "ok": False, "error": "invalid_op"})
            continue
        client_id = (op.get("client_id") or "").strip()
        try:
            ok, error = _sync_process_operation(user, op)
            results.append({"client_id": client_id, "ok": ok, "error": error})
        except Exception as exc:
            results.append({"client_id": client_id, "ok": False, "error": str(exc)})
    return jsonify({"ok": True, "results": results})
