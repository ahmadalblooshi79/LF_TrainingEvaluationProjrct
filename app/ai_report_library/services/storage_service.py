"""خدمة حفظ ملفات التقارير ومنع التكرار."""

from __future__ import annotations

import json
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.ai_report_library.models import AIReportSource
from app.ai_report_library.paths import (
    report_archived_dir,
    report_extracted_dir,
    report_original_dir,
)
from app.ai_report_library.security_upload import (
    ReportUploadError,
    sanitize_filename,
    sha256_bytes,
    sniff_file_type,
    validate_upload_filename,
    validate_upload_size,
)


def find_by_checksum(db: Session, checksum: str) -> AIReportSource | None:
    return (
        db.query(AIReportSource)
        .filter(
            AIReportSource.checksum == checksum,
            AIReportSource.is_active.is_(True),
            AIReportSource.processing_status != "archived",
        )
        .order_by(AIReportSource.id.desc())
        .first()
    )


def store_new_report(
    db: Session,
    *,
    file_bytes: bytes,
    original_filename: str,
    meta: dict[str, Any],
    user_id: int | None,
    force_new_version: bool = False,
) -> AIReportSource:
    validate_upload_size(len(file_bytes))
    ext = validate_upload_filename(original_filename)
    file_type = sniff_file_type(file_bytes, ext)
    checksum = sha256_bytes(file_bytes)
    existing = find_by_checksum(db, checksum)
    if existing and not force_new_version:
        raise ReportUploadError(
            f"هذا التقرير موجود مسبقاً في مكتبة التقارير (معرّف: {existing.public_id})."
        )

    public_id = uuid.uuid4().hex
    safe_name = sanitize_filename(original_filename)
    stored_name = f"original{ext}"
    orig_dir = report_original_dir(public_id)
    dest = orig_dir / stored_name
    dest.write_bytes(file_bytes)
    (orig_dir / "meta.json").write_text(
        json.dumps(
            {
                "original_file_name": original_filename,
                "sanitized": safe_name,
                "checksum": checksum,
                "uploaded_at": datetime.utcnow().isoformat(timespec="seconds"),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    report_extracted_dir(public_id)

    version = 1
    if existing and force_new_version:
        version = int(existing.version or 1) + 1

    row = AIReportSource(
        public_id=public_id,
        original_file_name=original_filename,
        stored_file_name=stored_name,
        stored_file_path=str(dest),
        file_type=file_type,
        file_size=len(file_bytes),
        checksum=checksum,
        report_title=(meta.get("report_title") or Path(original_filename).stem).strip(),
        exercise_name=(meta.get("exercise_name") or "").strip(),
        exercise_type=(meta.get("exercise_type") or "").strip(),
        report_type=(meta.get("report_type") or "other").strip(),
        report_year=_int_or_none(meta.get("report_year")),
        report_language=(meta.get("report_language") or "ar").strip() or "ar",
        classification_level=(meta.get("classification_level") or "").strip(),
        report_quality=(meta.get("report_quality") or "").strip(),
        is_approved=bool(meta.get("is_approved")),
        allow_learning=bool(meta.get("allow_learning", True)),
        main_unit_name=(meta.get("main_unit_name") or "").strip(),
        main_unit_level=(meta.get("main_unit_level") or "").strip(),
        admin_notes=(meta.get("admin_notes") or None),
        processing_status="uploaded",
        uploaded_by=user_id,
        uploaded_at=datetime.utcnow(),
        version=version,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def archive_report_files(report: AIReportSource) -> None:
    src = Path(report.stored_file_path)
    dest_dir = report_archived_dir(report.public_id)
    if src.is_file():
        shutil.copy2(src, dest_dir / src.name)


def _int_or_none(v: Any) -> int | None:
    if v is None or v == "":
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None
