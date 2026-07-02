"""قيم مشتركة للقوالب (التمرين في الهيدر: شريط فرعي + تسمية التمرين الحالي)."""
from __future__ import annotations

from flask import g, has_request_context, request, url_for

from sqlalchemy import desc, func

from app.auth import get_current_user_optional
from app.config import HEARTBEAT_FAST_POLL_MS, HEARTBEAT_POLL_MS
from app.models import Exercise, ExerciseNotification
from app.permissions import (
    can_access_analyst_hub,
    can_access_chief_judge_hub,
    can_access_control_hub,
    can_access_judge_hub,
    can_access_planner_hub,
    can_manage_information_bank,
    can_use_chat_rooms,
    can_view_information_bank,
    can_view_notifications_log,
    is_chief_judge,
    is_judge,
    is_system_admin,
)

# صفحات لا يُطبَّق عليها تدرج الأزرار العسكري الجديد (تبقى الألوان السابقة)
_HUB_LANDING_PRESERVE_BUTTON_ENDPOINTS = frozenset({
    "views.dashboard",
    "views.planner_hub",
    "views.control_hub",
    "views.judge_hub",
    "views.chief_judge_hub",
    "views.analyst_hub",
})


def _nav_show_judge_hub_link(user) -> bool:
    """مساحة المحكمين الموحدة — تشمل أيضاً أوامر كبير المحكمين عند منح الدور."""
    return bool(can_access_judge_hub(user))


def _is_individual_judge_user(user) -> bool:
    """محكم فردي — دون كبير المحكمين أو إدارة النظام."""
    return bool(is_judge(user) and not is_chief_judge(user) and not is_system_admin(user))


def _header_nav_path_active(prefix: str, *, path: str) -> bool:
    """هل المسار الحالي ينتمي لرابط الترويسة (الصفحة التابعة أو مساراتها الفرعية)؟"""
    norm = (path or "").rstrip("/") or "/"
    root = (prefix or "").rstrip("/") or "/"
    if root == "/dashboard":
        return norm in ("/", "/dashboard")
    return norm == root or norm.startswith(root + "/")


def inject_header_exercise():
    base = {
        "header_exercise": None,
        "workspace_exercise": None,
        "nav_role_hub_links": [],
        "judge_welcome_name": None,
        "notification_unread_count": 0,
        "notification_toast_seed": None,
        "notifications_log_url": None,
        "user_can_view_information_bank": False,
        "user_can_manage_information_bank": False,
        "header_chat_rooms_url": None,
        "header_exercise_info_url": None,
        "hub_landing_preserve_buttons": False,
        "hide_header_center_nav": False,
        "header_nav_dashboard_active": False,
        "header_nav_admin_active": False,
        "header_nav_library_active": False,
        "header_nav_chat_active": False,
        "header_nav_exercise_info_active": False,
        "header_nav_notifications_active": False,
        "header_admin_menu_active": {},
        "heartbeat_poll_ms": HEARTBEAT_POLL_MS,
        "heartbeat_fast_poll_ms": HEARTBEAT_FAST_POLL_MS,
    }

    if not has_request_context():
        return base
    if request.path.startswith("/static/"):
        return base
    if (request.path or "").startswith("/api/"):
        return base
    ep = request.endpoint or ""
    req_path = request.path or "/"
    base["hub_landing_preserve_buttons"] = ep in _HUB_LANDING_PRESERVE_BUTTON_ENDPOINTS
    base["header_nav_dashboard_active"] = _header_nav_path_active("/dashboard", path=req_path)
    base["header_nav_admin_active"] = req_path.startswith("/admin")
    base["header_nav_library_active"] = _header_nav_path_active("/library", path=req_path)
    base["header_nav_chat_active"] = _header_nav_path_active("/chat-rooms", path=req_path)
    base["header_nav_exercise_info_active"] = req_path.startswith("/exercises/")
    base["header_nav_notifications_active"] = _header_nav_path_active("/notifications", path=req_path)
    base["header_admin_menu_active"] = {
        "create": req_path.startswith("/admin/exercises/create"),
        "objectives": req_path.startswith("/admin/exercises/objectives"),
        "information_bank": req_path.startswith("/admin/information-bank"),
        "trainee_roster": req_path.startswith("/admin/exercises/trainee-unit-roster"),
        "judge_roster": req_path.startswith("/admin/exercises/judge-unit-roster"),
        "battle_org": req_path.startswith("/admin/battle-organization"),
        "users": req_path.startswith("/admin/users"),
        "server_management": req_path.startswith("/admin/server-management"),
    }
    db = getattr(g, "db", None)
    if db is None:
        return base

    u = get_current_user_optional()
    if u is not None:
        nav_hubs: list[dict[str, str]] = []

        def _push_hub(href: str, label: str, icon: str, can_fn) -> None:
            if not can_fn(u):
                return
            nav_hubs.append(
                {
                    "href": href,
                    "label": label,
                    "icon": icon,
                    "title": label,
                    "active": _header_nav_path_active(href, path=req_path),
                }
            )

        _push_hub("/planner", "التخطيط", "fa-calendar-check", can_access_planner_hub)
        _push_hub("/control", "السيطرة", "fa-eye", can_access_control_hub)
        _push_hub("/judge", "المحكمين", "fa-scale-balanced", _nav_show_judge_hub_link)
        _push_hub("/chief-judge", "كبير المحكمين", "fa-stamp", can_access_chief_judge_hub)
        _push_hub("/analyst", "المحللين", "fa-magnifying-glass-chart", can_access_analyst_hub)
        base["nav_role_hub_links"] = nav_hubs
        base["hide_header_center_nav"] = _is_individual_judge_user(u)
        base["user_can_view_information_bank"] = bool(can_view_information_bank(u))
        base["user_can_manage_information_bank"] = bool(can_manage_information_bank(u))
        if bool(can_use_chat_rooms(u)):
            base["header_chat_rooms_url"] = url_for("views.chat_rooms_list")

        if (is_judge(u) or is_chief_judge(u)) and not is_system_admin(u):
            nm = (getattr(u, "full_name", "") or "").strip() or (getattr(u, "username", "") or "").strip()
            base["judge_welcome_name"] = nm or ("كبير المحكمين" if is_chief_judge(u) else "محكم")

        # التمرين الحالي في الشريط العلوي — آخر تمرين في النظام (عادة تمرين واحد)
        ws = db.query(Exercise).order_by(Exercise.id.desc()).first()
        if ws is not None:
            base["workspace_exercise"] = {
                "id": ws.id,
                "title": ws.title,
                "code": ws.code,
            }
            base["header_exercise_info_url"] = url_for("views.exercise_detail", eid=int(ws.id))

        if can_view_notifications_log(u):
            if ws is not None:
                unread = (
                    db.query(func.count(ExerciseNotification.id))
                    .filter(
                        ExerciseNotification.user_id == u.id,
                        ExerciseNotification.exercise_id == ws.id,
                        ExerciseNotification.is_read == False,
                    )
                    .scalar()
                    or 0
                )
                base["notification_unread_count"] = int(unread)
                if int(unread) > 0:
                    seed_row = (
                        db.query(ExerciseNotification)
                        .filter(
                            ExerciseNotification.user_id == u.id,
                            ExerciseNotification.exercise_id == ws.id,
                            ExerciseNotification.is_read == False,
                        )
                        .order_by(
                            desc(ExerciseNotification.created_at),
                            desc(ExerciseNotification.id),
                        )
                        .first()
                    )
                    if seed_row is not None:
                        base["notification_toast_seed"] = {
                            "id": int(seed_row.id),
                            "title": seed_row.title or "",
                            "body": (seed_row.body or "")[:500],
                            "type": seed_row.type or "system",
                            "priority": seed_row.priority or "normal",
                            "is_read": False,
                            "action_url": seed_row.action_url or "",
                            "created_at": (
                                seed_row.created_at.isoformat()
                                if seed_row.created_at
                                else ""
                            ),
                        }
            base["notifications_log_url"] = url_for("views.notifications_log")

    row = None
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
