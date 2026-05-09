"""قيم مشتركة للقوالب (التمرين في الهيدر: شريط فرعي + تسمية التمرين الحالي)."""
from __future__ import annotations

from flask import g, has_request_context, request, url_for

from sqlalchemy import func

from app.auth import get_current_user_optional
from app.models import Exercise, ExerciseNotification
from app.permissions import (
    can_access_analyst_hub,
    can_access_control_hub,
    can_access_judge_hub,
    can_access_planner_hub,
    can_view_notifications_log,
    is_judge,
    is_system_admin,
)


def inject_header_exercise():
    base = {
        "header_exercise": None,
        "workspace_exercise": None,
        "nav_role_hub_links": [],
        "judge_welcome_name": None,
        "notification_unread_count": 0,
        "notifications_log_url": None,
    }

    if not has_request_context():
        return base
    if request.path.startswith("/static/"):
        return base
    db = getattr(g, "db", None)
    if db is None:
        return base

    u = get_current_user_optional()
    if u is not None:
        nav_hubs: list[dict[str, str]] = []

        def _push_hub(href: str, label: str, icon: str, can_fn) -> None:
            if not can_fn(u):
                return
            nav_hubs.append({"href": href, "label": label, "icon": icon, "title": label})

        _push_hub("/planner", "التخطيط", "fa-calendar-check", can_access_planner_hub)
        _push_hub("/control", "السيطرة", "fa-eye", can_access_control_hub)
        _push_hub("/judge", "المحكمين", "fa-scale-balanced", can_access_judge_hub)
        _push_hub("/analyst", "المحللين", "fa-magnifying-glass-chart", can_access_analyst_hub)
        base["nav_role_hub_links"] = nav_hubs

        if is_judge(u) and not is_system_admin(u):
            nm = (getattr(u, "full_name", "") or "").strip() or (getattr(u, "username", "") or "").strip()
            base["judge_welcome_name"] = nm or "محكم"

        ws = (
            db.query(Exercise)
            .filter(Exercise.owner_id == u.id)
            .order_by(Exercise.id.desc())
            .first()
        )
        if ws is not None:
            base["workspace_exercise"] = {
                "id": ws.id,
                "title": ws.title,
                "code": ws.code,
            }

        if can_view_notifications_log(u):
            if is_system_admin(u):
                n_ex = (
                    db.query(Exercise)
                    .filter(Exercise.owner_id == u.id)
                    .order_by(Exercise.id.desc())
                    .first()
                )
            else:
                n_ex = db.query(Exercise).order_by(Exercise.id.desc()).first()
            if n_ex is not None:
                unread = (
                    db.query(func.count(ExerciseNotification.id))
                    .filter(
                        ExerciseNotification.user_id == u.id,
                        ExerciseNotification.exercise_id == n_ex.id,
                        ExerciseNotification.is_read == False,
                    )
                    .scalar()
                    or 0
                )
                base["notification_unread_count"] = int(unread)
            base["notifications_log_url"] = url_for("views.notifications_log")

    row = None
    ep = request.endpoint
    if ep == "views.exercise_detail":
        eid = (request.view_args or {}).get("eid")
        if eid is not None:
            row = db.query(Exercise).filter(Exercise.id == int(eid)).first()
    elif ep == "views.admin_exercise_objectives":
        raw = (request.args.get("exercise_id") or "").strip()
        if raw.isdigit():
            row = db.query(Exercise).filter(Exercise.id == int(raw)).first()
        if row is None and u is not None:
            row = (
                db.query(Exercise)
                .filter(Exercise.owner_id == u.id)
                .order_by(Exercise.id.desc())
                .first()
            )
    elif ep in (
        "views.admin_exercise_trainee_unit_roster",
        "views.admin_exercise_judge_unit_roster",
    ):
        if u is not None:
            row = (
                db.query(Exercise)
                .filter(Exercise.owner_id == u.id)
                .order_by(Exercise.id.desc())
                .first()
            )
    elif ep == "views.admin_exercise_exports":
        raw = (request.args.get("exercise_id") or "").strip()
        if raw.isdigit():
            row = db.query(Exercise).filter(Exercise.id == int(raw)).first()

    if row is not None:
        base["header_exercise"] = {
            "id": row.id,
            "title": row.title,
            "code": row.code,
        }
    return base
