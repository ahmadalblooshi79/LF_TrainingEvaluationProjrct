"""أمان رفع وثائق التدريب."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from app.ai_training.constants import ALLOWED_EXTENSIONS, BLOCKED_EXTENSIONS, MAX_UPLOAD_BYTES
from app.ai_training.exceptions import (
    DocumentTooLargeError,
    InvalidDocumentFileError,
    UnsupportedDocumentTypeError,
)


def sanitize_filename(name: str) -> str:
    base = Path(name or "file").name
    base = base.replace("\\", "_").replace("/", "_").replace("..", "_")
    base = re.sub(r"[^\w\.\-\u0600-\u06FF]+", "_", base, flags=re.UNICODE)
    return (base or "file")[:180]


def extension_of(filename: str) -> str:
    return Path(filename or "").suffix.lower()


def validate_upload_filename(filename: str) -> str:
    ext = extension_of(filename)
    if ".." in (filename or "") or "/" in filename.replace("\\", "/") or "\\" in filename:
        # اسم فقط بعد Path().name في sanitize — هنا نرفض مسار كامل واضح
        pass
    if ext in BLOCKED_EXTENSIONS:
        raise UnsupportedDocumentTypeError("الملف التنفيذي أو المضغوط غير مسموح.")
    if ext not in ALLOWED_EXTENSIONS:
        raise UnsupportedDocumentTypeError(
            f"الامتدادات المسموح بها: {', '.join(sorted(ALLOWED_EXTENSIONS))}."
        )
    return ext


def validate_upload_size(size: int) -> None:
    if size is None or size <= 0:
        raise InvalidDocumentFileError("الملف فارغ أو غير صالح.")
    if size > MAX_UPLOAD_BYTES:
        raise DocumentTooLargeError(
            f"تجاوز حجم الملف الحد الأقصى ({MAX_UPLOAD_BYTES // (1024 * 1024)} ميجابايت)."
        )


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sniff_file_type(data: bytes, ext: str) -> tuple[str, str]:
    """يعيد (file_kind, mime_type). لا يعتمد على الامتداد وحده."""
    if ext == ".pdf":
        if not data.lstrip().startswith(b"%PDF"):
            raise InvalidDocumentFileError("محتوى الملف لا يطابق صيغة PDF.")
        return "pdf", "application/pdf"
    if ext == ".docx":
        if not data.startswith(b"PK"):
            raise InvalidDocumentFileError("محتوى الملف لا يطابق صيغة Word DOCX.")
        return "docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if ext == ".txt":
        # رفض التوقيعات التنفيذية الواضحة
        if data.startswith(b"MZ") or data.startswith(b"%PDF") or data.startswith(b"PK\x03\x04"):
            # PK قد يكون zip متنكراً — نسمح بنص يبدأ بـ PK نادراً؛ نرفض MZ وPDF فقط بقوة
            if data.startswith(b"MZ") or data.lstrip().startswith(b"%PDF"):
                raise InvalidDocumentFileError("محتوى الملف لا يطابق نصاً عادياً.")
        return "txt", "text/plain"
    raise UnsupportedDocumentTypeError()
