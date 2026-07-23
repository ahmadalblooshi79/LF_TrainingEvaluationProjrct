"""أمان رفع ملفات التقارير."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from app.ai_report_library.constants import (
    ALLOWED_EXTENSIONS,
    BLOCKED_EXTENSIONS,
    MAX_UPLOAD_BYTES,
)


class ReportUploadError(Exception):
    def __init__(self, message: str):
        self.user_message = message
        super().__init__(message)


def sanitize_filename(name: str) -> str:
    base = Path(name or "file").name
    base = base.replace("\\", "_").replace("/", "_").replace("..", "_")
    base = re.sub(r"[^\w\.\-\u0600-\u06FF]+", "_", base, flags=re.UNICODE)
    return (base or "file")[:180]


def extension_of(filename: str) -> str:
    return Path(filename or "").suffix.lower()


def validate_upload_filename(filename: str) -> str:
    ext = extension_of(filename)
    if ext in BLOCKED_EXTENSIONS:
        raise ReportUploadError("الملف غير مدعوم.")
    if ext not in ALLOWED_EXTENSIONS:
        raise ReportUploadError("الامتدادات المسموح بها: .docx و .pdf فقط.")
    return ext


def validate_upload_size(size: int) -> None:
    if size is None or size <= 0:
        raise ReportUploadError("الملف فارغ أو غير صالح.")
    if size > MAX_UPLOAD_BYTES:
        raise ReportUploadError(
            f"تجاوز حجم الملف الحد الأقصى ({MAX_UPLOAD_BYTES // (1024 * 1024)} ميجابايت)."
        )


def sha256_bytes(data: bytes) -> str:
    h = hashlib.sha256()
    h.update(data)
    return h.hexdigest()


def sniff_file_type(data: bytes, ext: str) -> str:
    """تحقق بسيط من التوقيع — لا يعتمد على الامتداد وحده."""
    if ext == ".pdf":
        if not data.lstrip().startswith(b"%PDF"):
            raise ReportUploadError("محتوى الملف لا يطابق صيغة PDF.")
        return "pdf"
    if ext == ".docx":
        # DOCX = ZIP/OOXML
        if not data.startswith(b"PK"):
            raise ReportUploadError("محتوى الملف لا يطابق صيغة Word DOCX.")
        return "docx"
    raise ReportUploadError("نوع الملف غير مدعوم.")
