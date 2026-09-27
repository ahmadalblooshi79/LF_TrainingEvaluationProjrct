"""واجهات التخطيط: إدارة أجهزة المحكمين واستيراد Excel."""
from __future__ import annotations

import uuid
from pathlib import Path

from flask import Blueprint, abort, flash, g, redirect, render_template, request, session, url_for

from app.auth import get_current_user_optional
from app.permissions import can_access_planner_hub, is_system_admin

bp = Blueprint("tablet_transfer", __name__)


def _require_planner():
    user = get_current_user_optional()
    if not user:
        abort(redirect(f"/login?next={request.path or '/planner/judge-tablets'}"))
    if not (can_access_planner_hub(user) or is_system_admin(user)):
        abort(403)
    return user


def _ctx(user, **extra):
    from app.views import _ctx as views_ctx, _planner_hub_back_ctx_always

    extra.update(_planner_hub_back_ctx_always())
    return views_ctx(user, **extra)


def _current_exercise(db, user):
    from app.views import _current_workspace_exercise

    return _current_workspace_exercise(db, user)


@bp.route("/planner/judge-tablets")
def planner_judge_tablets():
    user = _require_planner()
    db = g.db
    from app.models.server_monitor import ConnectedDevice
    from app.server_monitor.device_sessions import list_devices
    from app.tablet_transfer_ops import device_ui_status, probe_device, refresh_device_row

    rows = list_devices(db)
    cards = []
    for row in rows:
        probe = None
        if (row.status or "") == "online" and (row.device_ip or "").strip():
            probe = probe_device(row)
            if probe.get("ready"):
                refresh_device_row(db, row, probe)
        code, label = device_ui_status(row, probe)
        lists = []
        if probe and isinstance(probe.get("summary"), dict):
            lists = probe["summary"].get("lists") or probe["summary"].get("evaluations") or []
        cards.append(
            {
                "row": row,
                "status_code": code,
                "status_label": label,
                "ready": bool(probe and probe.get("ready")),
                "probe": probe or {},
                "lists": lists if isinstance(lists, list) else [],
            }
        )
    db.commit()
    ex = _current_exercise(db, user)
    return render_template(
        "planner_judge_tablets.html",
        **_ctx(
            user,
            cards=cards,
            exercise=ex,
            page_title="إدارة أجهزة المحكمين",
        ),
    )


@bp.route("/planner/judge-tablets/<device_id>")
def planner_judge_tablet_detail(device_id: str):
    user = _require_planner()
    db = g.db
    from app.models.server_monitor import ConnectedDevice
    from app.tablet_transfer_ops import device_ui_status, list_device_evaluations, probe_device, refresh_device_row

    row = (
        db.query(ConnectedDevice)
        .filter(ConnectedDevice.device_id == (device_id or "").strip())
        .one_or_none()
    )
    if row is None:
        abort(404)
    probe = probe_device(row)
    if probe.get("ready"):
        refresh_device_row(db, row, probe)
        db.commit()
    code, label = device_ui_status(row, probe)
    lists = []
    ev = list_device_evaluations(row) if probe.get("ready") else {}
    if isinstance(ev, dict):
        lists = ev.get("evaluations") or ev.get("lists") or []
    if not lists and isinstance(probe.get("summary"), dict):
        lists = probe["summary"].get("lists") or []
    return render_template(
        "planner_judge_tablet_detail.html",
        **_ctx(
            user,
            device=row,
            status_code=code,
            status_label=label,
            ready=bool(probe.get("ready")),
            probe=probe,
            lists=lists if isinstance(lists, list) else [],
            page_title=row.device_name or device_id,
        ),
    )


@bp.route("/planner/judge-tablets/<device_id>/pull", methods=["POST"])
def planner_judge_tablet_pull(device_id: str):
    user = _require_planner()
    db = g.db
    from app.models.server_monitor import ConnectedDevice
    from app.tablet_transfer_ops import pull_lists_preview

    row = (
        db.query(ConnectedDevice)
        .filter(ConnectedDevice.device_id == (device_id or "").strip())
        .one_or_none()
    )
    if row is None:
        abort(404)
    ids = []
    for raw in request.form.getlist("eval_item_id"):
        try:
            n = int(str(raw).strip())
        except (TypeError, ValueError):
            continue
        if n > 0:
            ids.append(n)
    if not ids:
        flash("حدّد قائمة واحدة على الأقل للسحب.", "error")
        return redirect(url_for("tablet_transfer.planner_judge_tablet_detail", device_id=device_id))
    ex = _current_exercise(db, user)
    result = pull_lists_preview(
        db,
        row,
        ids,
        current_exercise_id=int(ex.id) if ex is not None else None,
    )
    session["tablet_pull_preview"] = result
    session["tablet_pull_device"] = device_id
    return redirect(url_for("tablet_transfer.planner_judge_tablet_pull_preview", device_id=device_id))


@bp.route("/planner/judge-tablets/<device_id>/pull-preview")
def planner_judge_tablet_pull_preview(device_id: str):
    user = _require_planner()
    preview = session.get("tablet_pull_preview") or {}
    return render_template(
        "planner_tablet_pull_preview.html",
        **_ctx(
            user,
            device_id=device_id,
            preview=preview,
            page_title="معاينة سحب النتائج",
        ),
    )


@bp.route("/planner/judge-tablets/<device_id>/pull-confirm", methods=["POST"])
def planner_judge_tablet_pull_confirm(device_id: str):
    user = _require_planner()
    db = g.db
    from app.models.server_monitor import ConnectedDevice
    from app.tablet_transfer_ops import confirm_pull

    row = (
        db.query(ConnectedDevice)
        .filter(ConnectedDevice.device_id == (device_id or "").strip())
        .one_or_none()
    )
    if row is None:
        abort(404)
    preview = session.get("tablet_pull_preview") or {}
    jobs = preview.get("jobs") or []
    selected = []
    for raw in request.form.getlist("source_eval_item_id"):
        try:
            selected.append(int(str(raw).strip()))
        except (TypeError, ValueError):
            continue
    manual_map: dict[int, int] = {}
    for key, val in request.form.items():
        if key.startswith("map_"):
            try:
                src = int(key[4:])
                dst = int(str(val).strip())
            except (TypeError, ValueError):
                continue
            if src > 0 and dst > 0:
                manual_map[src] = dst
    overwrite = request.form.get("overwrite_approved") == "1"
    ex = _current_exercise(db, user)
    restored_total = 0
    errors = []
    for job in jobs:
        if not job.get("ok"):
            errors.append(f"#{job.get('eval_item_id')}: فشل السحب")
            continue
        try:
            out = confirm_pull(
                db,
                row,
                extract_dir=job.get("extract_dir") or "",
                package_hash=job.get("package_hash") or "",
                package_name=job.get("package_name") or "",
                selected_ids=selected,
                manual_map=manual_map,
                operator_id=int(user.id),
                current_exercise_id=int(ex.id) if ex is not None else None,
                overwrite_approved=overwrite,
                force=request.form.get("force") == "1",
            )
            restored_total += int(out.get("restored") or 0)
        except Exception as exc:
            errors.append(f"#{job.get('eval_item_id')}: {exc}")
    if errors:
        flash(" / ".join(errors), "error")
    else:
        flash(f"تم سحب {restored_total} قائمة.", "ok")
    session.pop("tablet_pull_preview", None)
    return redirect(url_for("tablet_transfer.planner_judge_tablet_detail", device_id=device_id))


@bp.route("/planner/judge-tablets/<device_id>/push", methods=["POST"])
def planner_judge_tablet_push(device_id: str):
    user = _require_planner()
    db = g.db
    from app.eval_identity_matcher import record_transfer_audit
    from app.models.server_monitor import ConnectedDevice
    from app.tablet_transfer_ops import push_to_device

    row = (
        db.query(ConnectedDevice)
        .filter(ConnectedDevice.device_id == (device_id or "").strip())
        .one_or_none()
    )
    if row is None:
        abort(404)
    ids = []
    for raw in request.form.getlist("eval_item_id"):
        try:
            n = int(str(raw).strip())
        except (TypeError, ValueError):
            continue
        if n > 0:
            ids.append(n)
    scope = "lists" if ids else "all"
    result = push_to_device(row, eval_item_ids=ids, scope=scope)
    if result.get("code") == "LOCAL_WORK_EXISTS" or result.get("status") == "LOCAL_WORK_EXISTS":
        flash("يوجد عمل محلي على الجهاز لم يتم استلامه.", "error")
        session["tablet_local_work"] = result
        return redirect(url_for("tablet_transfer.planner_judge_tablet_detail", device_id=device_id))
    if result.get("ok") or result.get("http") == 200:
        record_transfer_audit(
            db,
            operation_type="SERVER_PUSH",
            device_id=row.device_id,
            judge_id=row.user_id,
            unit_id=getattr(row, "unit_key", "") or "",
            exercise_id=getattr(row, "exercise_id", None),
            operator_id=int(user.id),
            details=str(ids),
        )
        db.commit()
        flash("تم إرسال التحديث إلى التابلت.", "ok")
    else:
        flash(f"فشل التحديث: {result.get('error') or result.get('http')}", "error")
    return redirect(url_for("tablet_transfer.planner_judge_tablet_detail", device_id=device_id))


@bp.route("/planner/tablet-excel-import", methods=["GET"])
def planner_tablet_excel_import():
    user = _require_planner()
    db = g.db
    from app.models import EvaluationListPdfItem
    from app.tablet_excel_import import build_import_preview

    extract = (session.get("tablet_excel_extract") or "").strip()
    package_hash = (session.get("tablet_excel_hash") or "").strip()
    package_name = (session.get("tablet_excel_name") or "").strip()
    preview = None
    catalog = []
    ex = _current_exercise(db, user)
    if extract and Path(extract).is_dir() and package_hash:
        preview = build_import_preview(
            db,
            Path(extract),
            package_hash=package_hash,
            package_name=package_name,
            current_exercise_id=int(ex.id) if ex is not None else None,
        )
    if ex is not None:
        catalog = (
            db.query(EvaluationListPdfItem)
            .filter(EvaluationListPdfItem.exercise_id == int(ex.id))
            .order_by(EvaluationListPdfItem.unit_level_key, EvaluationListPdfItem.sort_order)
            .all()
        )
    return render_template(
        "planner_tablet_excel_import.html",
        **_ctx(
            user,
            preview=preview,
            catalog=catalog,
            page_title="استيراد نتائج من التابلت",
        ),
    )


@bp.route("/planner/tablet-excel-import/upload", methods=["POST"])
def planner_tablet_excel_import_upload():
    user = _require_planner()
    from app.tablet_excel_import import _uploads_root, extract_import_archive, sha256_file

    f = request.files.get("package")
    if f is None or not (f.filename or "").strip():
        flash("اختر ملف Excel أو حزمة ZIP.", "error")
        return redirect(url_for("tablet_transfer.planner_tablet_excel_import"))
    dest_root = _uploads_root() / uuid.uuid4().hex
    dest_root.mkdir(parents=True, exist_ok=True)
    name = (f.filename or "import.bin").strip()
    suffix = Path(name).suffix.lower()
    if suffix not in {".xlsx", ".zip"}:
        flash("يُقبل .xlsx أو .zip فقط.", "error")
        return redirect(url_for("tablet_transfer.planner_tablet_excel_import"))
    stored = dest_root / f"upload{suffix}"
    f.save(str(stored))
    extract_dir = dest_root / "extracted"
    try:
        extract_import_archive(stored, extract_dir)
    except Exception as exc:
        flash(f"تعذّر فتح الملف: {exc}", "error")
        return redirect(url_for("tablet_transfer.planner_tablet_excel_import"))
    session["tablet_excel_extract"] = str(extract_dir)
    session["tablet_excel_hash"] = sha256_file(stored)
    session["tablet_excel_name"] = name
    return redirect(url_for("tablet_transfer.planner_tablet_excel_import"))


@bp.route("/planner/tablet-excel-import/apply", methods=["POST"])
def planner_tablet_excel_import_apply():
    user = _require_planner()
    db = g.db
    from app.tablet_excel_import import apply_import, build_import_preview

    extract = (session.get("tablet_excel_extract") or "").strip()
    package_hash = (session.get("tablet_excel_hash") or "").strip()
    package_name = (session.get("tablet_excel_name") or "").strip()
    if not extract or not Path(extract).is_dir():
        flash("ارفع ملفاً أولاً ثم عاين المطابقة.", "error")
        return redirect(url_for("tablet_transfer.planner_tablet_excel_import"))
    ex = _current_exercise(db, user)
    preview = build_import_preview(
        db,
        Path(extract),
        package_hash=package_hash,
        package_name=package_name,
        current_exercise_id=int(ex.id) if ex is not None else None,
    )
    selected = []
    for raw in request.form.getlist("source_eval_item_id"):
        try:
            selected.append(int(str(raw).strip()))
        except (TypeError, ValueError):
            continue
    manual_map: dict[int, int] = {}
    for key, val in request.form.items():
        if key.startswith("map_"):
            try:
                src = int(key[4:])
                dst = int(str(val).strip())
            except (TypeError, ValueError):
                continue
            if src > 0 and dst > 0:
                manual_map[src] = dst
    try:
        out = apply_import(
            db,
            preview,
            selected_source_ids=selected,
            manual_map=manual_map,
            operator_id=int(user.id),
            current_exercise_id=int(ex.id) if ex is not None else None,
            operation_type="EXCEL_IMPORT",
            force=request.form.get("force") == "1",
            overwrite_approved=request.form.get("overwrite_approved") == "1",
        )
    except Exception as exc:
        flash(str(exc), "error")
        return redirect(url_for("tablet_transfer.planner_tablet_excel_import"))
    flash(
        f"تم الاستيراد: {out.get('restored', 0)} قائمة، تخطي {out.get('skipped', 0)}، وسائط {out.get('media', 0)}.",
        "ok",
    )
    return redirect(url_for("tablet_transfer.planner_tablet_excel_import"))
