"""عمليات سحب/دفع نتائج التابلت من الخادم — كل جهاز مستقل."""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.models.server_monitor import ConnectedDevice
from app.tablet_excel_import import apply_import, build_import_preview, extract_import_archive, sha256_bytes
from app.tablet_lan_client import (
    ack_received,
    get_evaluations,
    get_summary,
    probe_health,
    pull_evaluation_package,
    push_update,
)

READY_LABELS = {
    "OFFLINE": "غير متصل",
    "ONLINE": "متصل",
    "READY": "جاهز",
    "HAS_LOCAL_WORK": "يوجد عمل محلي",
    "NEEDS_UPDATE": "يحتاج تحديث",
    "PULLING": "جاري السحب",
    "PUSHING": "جاري التحديث",
    "FAILED": "فشل الاتصال",
    "CONFLICT": "تعارض",
    "UNREACHABLE": "غير متصل",
    "NOT_READY": "متصل",
}


def device_ui_status(row: ConnectedDevice, probe: dict[str, Any] | None = None) -> tuple[str, str]:
    if (getattr(row, "status", "") or "") != "online":
        return "OFFLINE", READY_LABELS["OFFLINE"]
    if probe is None:
        return "ONLINE", READY_LABELS["ONLINE"]
    if probe.get("ready"):
        pending = int(probe.get("pending_saves") or probe.get("local_pending_saves") or getattr(row, "local_pending_saves", 0) or 0)
        saved = int(probe.get("saved_count") or getattr(row, "local_saved_count", 0) or 0)
        if pending or saved:
            return "HAS_LOCAL_WORK", READY_LABELS["HAS_LOCAL_WORK"]
        return "READY", READY_LABELS["READY"]
    code = (probe.get("status") or "NOT_READY").upper()
    if code in ("UNREACHABLE", "FAILED"):
        return "FAILED", READY_LABELS["FAILED"]
    return "NOT_READY", READY_LABELS["NOT_READY"]


def probe_device(row: ConnectedDevice) -> dict[str, Any]:
    ip = (row.device_ip or "").strip()
    token = getattr(row, "local_api_token", "") or ""
    port = int(getattr(row, "local_api_port", 0) or 8765)
    if not ip or not token:
        return {"ready": False, "status": "NOT_READY", "error": "missing_ip_or_token"}
    health = probe_health(ip, token, port=port)
    if not health.get("ready"):
        return health
    ident = get_identity(ip, token, port=port)
    summary = get_summary(ip, token, port=port)
    out = {**health}
    if isinstance(ident, dict) and ident.get("ok") is not False:
        out["identity"] = ident
    if isinstance(summary, dict) and summary.get("ok") is not False:
        out["summary"] = summary
        out["pending_saves"] = summary.get("pending_saves") or summary.get("local_pending_saves")
        out["saved_count"] = summary.get("saved_count") or summary.get("local_saved_count")
        out["lists"] = summary.get("lists") or summary.get("evaluations") or []
    return out


def refresh_device_row(db: Session, row: ConnectedDevice, probe: dict[str, Any]) -> None:
    ident = probe.get("identity") if isinstance(probe.get("identity"), dict) else {}
    summary = probe.get("summary") if isinstance(probe.get("summary"), dict) else {}
    if ident.get("unit_id"):
        row.unit_key = str(ident.get("unit_id") or "")[:128]
    if ident.get("unit_name"):
        row.unit_label = str(ident.get("unit_name") or "")[:256]
    if ident.get("exercise_id"):
        try:
            row.exercise_id = int(ident.get("exercise_id"))
        except (TypeError, ValueError):
            pass
    if ident.get("exercise_name"):
        row.exercise_name = str(ident.get("exercise_name") or "")[:256]
    if ident.get("app_version"):
        row.app_version = str(ident.get("app_version") or "")[:64]
    if ident.get("package_version"):
        row.package_version = str(ident.get("package_version") or "")[:64]
    if ident.get("device_name"):
        row.device_name = str(ident.get("device_name") or row.device_name)[:256]
    if ident.get("judge_name"):
        row.judge_name = str(ident.get("judge_name") or row.judge_name)[:256]
    row.local_saved_count = int(summary.get("saved_count") or summary.get("local_saved_count") or 0)
    row.local_pending_saves = int(summary.get("pending_saves") or summary.get("local_pending_saves") or 0)


def pull_lists_preview(
    db: Session,
    row: ConnectedDevice,
    eval_item_ids: list[int],
    *,
    current_exercise_id: int | None,
) -> dict[str, Any]:
    ip = (row.device_ip or "").strip()
    token = getattr(row, "local_api_token", "") or ""
    port = int(getattr(row, "local_api_port", 0) or 8765)
    jobs = []
    for eid in eval_item_ids:
        status, payload = pull_evaluation_package(ip, token, int(eid), port=port)
        if status != 200 or not isinstance(payload, (bytes, bytearray)):
            jobs.append(
                {
                    "eval_item_id": eid,
                    "ok": False,
                    "error": payload if isinstance(payload, dict) else "pull_failed",
                }
            )
            continue
        tmp = Path(tempfile.mkdtemp(prefix="tablet_pull_"))
        zip_path = tmp / f"eval_{eid}.zip"
        zip_path.write_bytes(payload)
        extract = tmp / "extracted"
        extract_import_archive(zip_path, extract)
        preview = build_import_preview(
            db,
            extract,
            package_hash=sha256_bytes(bytes(payload)),
            package_name=f"pull-{row.device_id}-{eid}",
            current_exercise_id=current_exercise_id,
        )
        jobs.append(
            {
                "eval_item_id": eid,
                "ok": True,
                "extract_dir": str(extract),
                "package_hash": preview.package_hash,
                "package_name": preview.package_name,
                "items": [i.to_dict() for i in preview.items],
                "warnings": preview.warnings,
            }
        )
    return {"device_id": row.device_id, "jobs": jobs}


def confirm_pull(
    db: Session,
    row: ConnectedDevice,
    *,
    extract_dir: str,
    package_hash: str,
    package_name: str,
    selected_ids: list[int],
    manual_map: dict[int, int],
    operator_id: int | None,
    current_exercise_id: int | None,
    overwrite_approved: bool = False,
    force: bool = False,
) -> dict[str, int]:
    from app.tablet_excel_import import build_import_preview

    preview = build_import_preview(
        db,
        Path(extract_dir),
        package_hash=package_hash,
        package_name=package_name,
        current_exercise_id=current_exercise_id,
    )
    result = apply_import(
        db,
        preview,
        selected_source_ids=selected_ids,
        manual_map=manual_map,
        operator_id=operator_id,
        current_exercise_id=current_exercise_id,
        operation_type="SERVER_PULL",
        force=force,
        overwrite_approved=overwrite_approved,
    )
    ack_ids = selected_ids or [
        int(i.source.eval_item_id)
        for i in preview.items
        if i.source.eval_item_id
    ]
    try:
        ack_received(
            row.device_ip,
            getattr(row, "local_api_token", "") or "",
            eval_item_ids=ack_ids,
            port=int(getattr(row, "local_api_port", 0) or 8765),
        )
    except Exception:
        pass
    return result


def push_to_device(
    row: ConnectedDevice,
    *,
    eval_item_ids: list[int] | None = None,
    scope: str = "all",
) -> dict[str, Any]:
    return push_update(
        row.device_ip,
        getattr(row, "local_api_token", "") or "",
        eval_item_ids=eval_item_ids,
        scope=scope,
        port=int(getattr(row, "local_api_port", 0) or 8765),
    )


def list_device_evaluations(row: ConnectedDevice) -> dict[str, Any]:
    return get_evaluations(
        row.device_ip,
        getattr(row, "local_api_token", "") or "",
        port=int(getattr(row, "local_api_port", 0) or 8765),
    )
