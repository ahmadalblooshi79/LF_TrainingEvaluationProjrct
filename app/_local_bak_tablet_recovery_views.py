# -*- coding: utf-8 -*-
"""واجهات إدارة النظام — استعادة بيانات التابلت."""
from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

from flask import (
    Blueprint,
    abort,
    flash,
    g,
    redirect,
    render_template,
    request,
    url_for,
)
from werkzeug.utils import secure_filename

from app.auth import get_current_user_optional
from app.models.domain import TabletRecoveryImport
from app.permissions import is_system_admin
from app.tablet_recovery.parser import (
    RecoveryPackageError,
    parse_recovery_zip,
    sha256_file,
)
from app.tablet_recovery.preview import build_recovery_preview
from app.tablet_recovery.restore import restore_selected_evaluations
from app.tablet_recovery.storage import (
    archive_original_zip,
    ensure_recovery_dirs,
    new_staging_dir,
    recovery_root,
)

bp = Blueprint("tablet_recovery", __name__)


def _require_admin():
    user = get_current_user_optional()
    if not user or not is_system_admin(user):
        abort(403)
    return user


def _package_from_staging(staging_rel: str):
    staging = recovery_root() / staging_rel
    if not staging.is_dir():
        raise RecoveryPackageError("مجلد المعاينة غير موجود أو انتهت صلاحيته")
    # Re-parse from staging by wrapping as zip is heavy — rebuild package from files
    # Use a temporary approach: parse_recovery_zip needs a zip. Instead load via helper.
    from app.tablet_recovery.parser import (
        RecoveryPackage,
        _load_json,
        _map_cache,
        _map_media,
        _map_pending,
        _resolve_media_physical,
    )

    manifest = _load_json(staging / "manifest.json")
    pending_raw = _load_json(staging / "data" / "pending_ops.json")
    if isinstance(pending_raw, dict):
        ops_list = pending_raw.get("operations") or pending_raw.get("pending_ops") or []
    else:
        ops_list = pending_raw if isinstance(pending_raw, list) else []
    pending_ops = [_map_pending(e) for e in ops_list if isinstance(e, dict)]

    cache_evals = []
    cache_path = staging / "data" / "cache_evaluations.json"
    if cache_path.is_file():
        cache_raw = _load_json(cache_path)
        entries = (
            cache_raw.get("entries")
            if isinstance(cache_raw, dict)
            else (cache_raw if isinstance(cache_raw, list) else [])
        )
        cache_evals = [_map_cache(e) for e in entries if isinstance(e, dict)]

    media = []
    media_path = staging / "data" / "media_manifest.json"
    if media_path.is_file():
        media_raw = _load_json(media_path)
        records = (
            media_raw.get("records")
            if isinstance(media_raw, dict)
            else (media_raw if isinstance(media_raw, list) else [])
        )
        for e in records:
            if not isinstance(e, dict):
                continue
            m = _map_media(e)
            m.physical_path = _resolve_media_physical(staging, m)
            media.append(m)

    approvals = []
    ap_path = staging / "data" / "approvals.json"
    if ap_path.is_file():
        try:
            ap_raw = _load_json(ap_path)
            if isinstance(ap_raw, dict):
                approvals = [
                    dict(x) for x in (ap_raw.get("approvals") or []) if isinstance(x, dict)
                ]
        except Exception:
            pass

    return RecoveryPackage(
        manifest=manifest if isinstance(manifest, dict) else {},
        pending_ops=pending_ops,
        cache_evals=cache_evals,
        media=media,
        approvals=approvals,
        member_names=[],
        staging_dir=staging,
        has_excel=(staging / "Recovery_Report.xlsx").is_file(),
        parse_warnings=[],
    )


@bp.route("/admin/tablet-recovery", methods=["GET"])
def tablet_recovery_home():
    user = _require_admin()
    ensure_recovery_dirs()
    recent = (
        g.db.query(TabletRecoveryImport)
        .order_by(TabletRecoveryImport.imported_at.desc())
        .limit(15)
        .all()
    )
    return render_template(
        "admin_tablet_recovery.html",
        user=user,
        recent_imports=recent,
        preview=None,
        import_row=None,
        result=None,
    )


@bp.route("/admin/tablet-recovery/upload", methods=["POST"])
def tablet_recovery_upload():
    user = _require_admin()
    f = request.files.get("recovery_zip")
    if f is None or not (f.filename or "").strip():
        flash("اختر ملف ZIP لحزمة الاستعادة.", "error")
        return redirect(url_for("tablet_recovery.tablet_recovery_home"))
    filename = secure_filename(f.filename or "recovery.zip")
    if not filename.lower().endswith(".zip"):
        flash("يُقبل ملف ZIP فقط.", "error")
        return redirect(url_for("tablet_recovery.tablet_recovery_home"))

    ensure_recovery_dirs()
    staging = new_staging_dir()
    tmp_zip = staging / "_upload.zip"
    f.save(tmp_zip)

    try:
        package_hash = sha256_file(tmp_zip)
        prior = (
            g.db.query(TabletRecoveryImport)
            .filter(TabletRecoveryImport.package_hash == package_hash)
            .order_by(TabletRecoveryImport.imported_at.desc())
            .first()
        )
        package = parse_recovery_zip(tmp_zip, staging)
        archived = archive_original_zip(
            tmp_zip, package_hash=package_hash, original_name=filename
        )
        # remove upload copy inside staging (original is archived)
        try:
            tmp_zip.unlink(missing_ok=True)
        except TypeError:
            if tmp_zip.exists():
                tmp_zip.unlink()

        preview = build_recovery_preview(g.db, package)
        import_uuid = uuid.uuid4().hex
        staging_rel = str(staging.relative_to(recovery_root())).replace("\\", "/")
        archive_rel = str(archived.relative_to(recovery_root())).replace("\\", "/")

        row = TabletRecoveryImport(
            import_uuid=import_uuid,
            package_filename=filename[:400],
            package_hash=package_hash,
            device_id=str(preview.get("manifest", {}).get("device_id") or "")[:120],
            exercise_id=preview.get("manifest", {}).get("exercise_id"),
            judge_id=preview.get("manifest", {}).get("judge_id"),
            export_timestamp=str(
                preview.get("manifest", {}).get("export_timestamp") or ""
            )[:64],
            imported_by_id=int(user.id),
            status="preview",
            evaluation_count=int(preview.get("summary", {}).get("evaluation_count") or 0),
            media_count=int(preview.get("summary", {}).get("media_count") or 0),
            conflict_count=int(preview.get("summary", {}).get("conflict_count") or 0),
            archive_relpath=archive_rel[:700],
            staging_relpath=staging_rel[:700],
            preview_json=json.dumps(preview, ensure_ascii=False),
            notes=(
                f"حزمة مستخدمة سابقاً في {prior.imported_at.isoformat()} (حالة: {prior.status})"
                if prior is not None
                else ""
            ),
        )
        g.db.add(row)
        g.db.commit()
        return redirect(
            url_for("tablet_recovery.tablet_recovery_preview", import_uuid=import_uuid)
        )
    except RecoveryPackageError as exc:
        g.db.rollback()
        shutil.rmtree(staging, ignore_errors=True)
        flash(f"فشل فحص الحزمة: {exc}", "error")
        return redirect(url_for("tablet_recovery.tablet_recovery_home"))
    except Exception as exc:
        g.db.rollback()
        shutil.rmtree(staging, ignore_errors=True)
        flash(f"خطأ أثناء فحص الحزمة: {exc}", "error")
        return redirect(url_for("tablet_recovery.tablet_recovery_home"))


@bp.route("/admin/tablet-recovery/preview/<import_uuid>", methods=["GET"])
def tablet_recovery_preview(import_uuid: str):
    user = _require_admin()
    row = (
        g.db.query(TabletRecoveryImport)
        .filter(TabletRecoveryImport.import_uuid == import_uuid)
        .first()
    )
    if row is None:
        flash("المعاينة غير موجودة.", "error")
        return redirect(url_for("tablet_recovery.tablet_recovery_home"))
    try:
        preview = json.loads(row.preview_json or "{}")
    except Exception:
        preview = {}
    prior_same_hash = (
        g.db.query(TabletRecoveryImport)
        .filter(
            TabletRecoveryImport.package_hash == row.package_hash,
            TabletRecoveryImport.id != row.id,
        )
        .order_by(TabletRecoveryImport.imported_at.desc())
        .first()
    )
    return render_template(
        "admin_tablet_recovery.html",
        user=user,
        recent_imports=[],
        preview=preview,
        import_row=row,
        prior_same_hash=prior_same_hash,
        result=None,
        detail_item=None,
    )


@bp.route(
    "/admin/tablet-recovery/preview/<import_uuid>/item/<int:item_id>",
    methods=["GET"],
)
def tablet_recovery_item_detail(import_uuid: str, item_id: int):
    user = _require_admin()
    row = (
        g.db.query(TabletRecoveryImport)
        .filter(TabletRecoveryImport.import_uuid == import_uuid)
        .first()
    )
    if row is None:
        abort(404)
    preview = json.loads(row.preview_json or "{}")
    detail = None
    for e in preview.get("evaluations") or []:
        if int(e.get("eval_item_id") or 0) == int(item_id):
            detail = e
            break
    return render_template(
        "admin_tablet_recovery.html",
        user=user,
        recent_imports=[],
        preview=preview,
        import_row=row,
        prior_same_hash=None,
        result=None,
        detail_item=detail,
    )


@bp.route("/admin/tablet-recovery/restore/<import_uuid>", methods=["POST"])
def tablet_recovery_restore(import_uuid: str):
    user = _require_admin()
    row = (
        g.db.query(TabletRecoveryImport)
        .filter(TabletRecoveryImport.import_uuid == import_uuid)
        .first()
    )
    if row is None:
        flash("المعاينة غير موجودة.", "error")
        return redirect(url_for("tablet_recovery.tablet_recovery_home"))
    if row.status == "restored":
        # السماح بإعادة التشغيل لاستعادة وسائط ناقصة فقط (idempotent)
        flash(
            "هذه المعاينة نُفّذت سابقاً — ستُستعاد الوسائط الناقصة فقط إن وُجدت، دون تكرار النتائج.",
            "ok",
        )

    selected = request.form.getlist("eval_item_id")
    selected_ids = []
    for s in selected:
        try:
            selected_ids.append(int(s))
        except Exception:
            pass
    if not selected_ids:
        flash("حدّد قائمة واحدة على الأقل للاستعادة.", "error")
        return redirect(
            url_for("tablet_recovery.tablet_recovery_preview", import_uuid=import_uuid)
        )

    preview = json.loads(row.preview_json or "{}")
    try:
        package = _package_from_staging(row.staging_relpath)
        result = restore_selected_evaluations(
            g.db,
            package,
            preview,
            selected_item_ids=selected_ids,
            restore_approvals=False,
        )
        row.status = "restored"
        row.restored_evaluation_count = int(result.get("restored") or 0)
        row.restored_media_count = int(result.get("media_restored") or 0)
        row.result_json = json.dumps(result, ensure_ascii=False)
        g.db.commit()
        return render_template(
            "admin_tablet_recovery.html",
            user=user,
            recent_imports=[],
            preview=preview,
            import_row=row,
            prior_same_hash=None,
            result=result,
            detail_item=None,
        )
    except Exception as exc:
        g.db.rollback()
        flash(f"فشلت الاستعادة وتم التراجع: {exc}", "error")
        return redirect(
            url_for("tablet_recovery.tablet_recovery_preview", import_uuid=import_uuid)
        )
