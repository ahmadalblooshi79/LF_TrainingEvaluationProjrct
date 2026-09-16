"""توقيع إلكتروني للمحكم — PNG شفاف مرتبط بـ user_id ولقطة ثابتة عند الاعتماد."""
from __future__ import annotations

import base64
import io
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.domain import (
    EvaluationListSavedResult,
    JudgeElectronicSignature,
    PlannerFlowBundleEvalSavedResult,
)

SIGNATURE_INK_RGB = (23, 54, 93)  # #17365D
SIGNATURE_STATUS_REGISTERED = "registered"
MAX_SIGNATURE_PNG_BYTES = 900_000
SNAPSHOT_KIND_EVAL_LIST = "el"
SNAPSHOT_KIND_PLANNER = "pf"

NO_SIGNATURE_MESSAGE = (
    "لا يوجد توقيع إلكتروني مسجل لهذا الحساب.\n"
    "يرجى تسجيل التوقيع قبل اعتماد القائمة."
)
OWNER_MISMATCH_MESSAGE = (
    "تعذّر الاعتماد: التوقيع لا يخص الحساب الحالي."
)
INVALID_PNG_MESSAGE = "ملف التوقيع غير صالح. يُطلب PNG بخلفية شفافة."


class JudgeSignatureError(Exception):
    def __init__(self, message: str, code: str = "no_signature"):
        super().__init__(message)
        self.message = message
        self.code = code


def _png_ihdr_color_type(data: bytes) -> int | None:
    if len(data) < 25 or data[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    # IHDR: 8 sig + 4 len + 4 type + 4 width + 4 height + 1 bit + 1 color
    if data[12:16] != b"IHDR":
        return None
    return data[25]


def png_is_rgba(data: bytes) -> bool:
    return _png_ihdr_color_type(data) == 6


def decode_png_b64(raw: Any) -> bytes:
    if raw is None:
        raise JudgeSignatureError(INVALID_PNG_MESSAGE, "invalid_png")
    if isinstance(raw, bytes):
        blob = raw
    else:
        s = str(raw).strip()
        if not s:
            raise JudgeSignatureError(INVALID_PNG_MESSAGE, "invalid_png")
        if "," in s and s.lower().startswith("data:"):
            s = s.split(",", 1)[1]
        try:
            blob = base64.b64decode(s, validate=False)
        except Exception as exc:
            raise JudgeSignatureError(INVALID_PNG_MESSAGE, "invalid_png") from exc
    if not blob or len(blob) > MAX_SIGNATURE_PNG_BYTES:
        raise JudgeSignatureError(INVALID_PNG_MESSAGE, "invalid_png")
    return blob


def validate_transparent_signature_png(data: bytes) -> bytes:
    """يرفض أي صورة بلا قناة ألفا أو بخلفية بيضاء معتمة."""
    if not png_is_rgba(data):
        raise JudgeSignatureError(INVALID_PNG_MESSAGE, "invalid_png")
    try:
        from PIL import Image
    except Exception as exc:
        raise JudgeSignatureError(INVALID_PNG_MESSAGE, "invalid_png") from exc
    try:
        im = Image.open(io.BytesIO(data))
        im.load()
    except Exception as exc:
        raise JudgeSignatureError(INVALID_PNG_MESSAGE, "invalid_png") from exc
    if im.format not in (None, "PNG"):
        raise JudgeSignatureError(INVALID_PNG_MESSAGE, "invalid_png")
    if im.mode != "RGBA":
        raise JudgeSignatureError(INVALID_PNG_MESSAGE, "invalid_png")
    pixels = list(im.getdata())
    if not pixels:
        raise JudgeSignatureError(INVALID_PNG_MESSAGE, "invalid_png")
    transparent = 0
    ink = 0
    opaque_white = 0
    for r, g, b, a in pixels:
        if a < 16:
            transparent += 1
            continue
        if r > 240 and g > 240 and b > 240 and a > 200:
            opaque_white += 1
            continue
        if a > 140:
            ink += 1
    if transparent < max(8, len(pixels) // 40):
        raise JudgeSignatureError(INVALID_PNG_MESSAGE, "invalid_png")
    if ink < 8:
        raise JudgeSignatureError(INVALID_PNG_MESSAGE, "invalid_png")
    if opaque_white > max(ink * 4, len(pixels) // 8):
        raise JudgeSignatureError(INVALID_PNG_MESSAGE, "invalid_png")
    return data


def make_sample_signature_png(*, width: int = 220, height: int = 80) -> bytes:
    """PNG اختبار بخلفية شفافة وحبر أزرق داكن."""
    from PIL import Image, ImageDraw

    im = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(im)
    ink = (*SIGNATURE_INK_RGB, 255)
    draw.line((18, 52, 70, 28, 120, 58, 200, 24), fill=ink, width=3)
    draw.line((40, 60, 90, 36), fill=ink, width=3)
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def get_master(db: Session, user_id: int | None) -> JudgeElectronicSignature | None:
    if not user_id:
        return None
    return (
        db.query(JudgeElectronicSignature)
        .filter(JudgeElectronicSignature.user_id == int(user_id))
        .first()
    )


def master_png_bytes(row: JudgeElectronicSignature | None) -> bytes | None:
    if row is None:
        return None
    blob = row.png_blob
    if not blob:
        return None
    return bytes(blob)


def save_or_replace_master(
    db: Session,
    user_id: int,
    png_bytes: bytes,
    *,
    source: str = "tablet",
    replace: bool = False,
) -> JudgeElectronicSignature:
    uid = int(user_id)
    png_bytes = validate_transparent_signature_png(png_bytes)
    now = datetime.utcnow()
    row = get_master(db, uid)
    if row is None:
        row = JudgeElectronicSignature(
            user_id=uid,
            png_blob=png_bytes,
            version=1,
            status=SIGNATURE_STATUS_REGISTERED,
            source=(source or "tablet")[:32],
            registered_at=now,
            updated_at=now,
        )
        db.add(row)
        db.flush()
        return row
    if not replace:
        raise JudgeSignatureError(
            "يوجد توقيع إلكتروني مسجل مسبقاً. هل تريد استبداله؟",
            "exists",
        )
    row.png_blob = png_bytes
    row.version = int(row.version or 1) + 1
    row.status = SIGNATURE_STATUS_REGISTERED
    row.source = (source or row.source or "tablet")[:32]
    row.updated_at = now
    db.flush()
    return row


def ensure_master_from_snapshot(
    db: Session,
    user_id: int,
    png_bytes: bytes,
    *,
    source: str = "tablet",
) -> JudgeElectronicSignature:
    """إن لم يوجد توقيع رئيسي بعد (مزامنة اعتماد أوفلاين) يُنشأ من اللقطة."""
    row = get_master(db, user_id)
    if row is not None and master_png_bytes(row):
        return row
    return save_or_replace_master(
        db, user_id, png_bytes, source=source, replace=True
    )


def attach_signature_snapshot(
    saved: EvaluationListSavedResult | PlannerFlowBundleEvalSavedResult,
    *,
    user_id: int,
    png_bytes: bytes,
    version: int,
) -> None:
    png_bytes = validate_transparent_signature_png(png_bytes)
    saved.signature_user_id = int(user_id)
    saved.signature_version = int(version)
    saved.signature_png = png_bytes
    saved.signature_registered_at = datetime.utcnow()


def clear_signature_snapshot(
    saved: EvaluationListSavedResult | PlannerFlowBundleEvalSavedResult,
) -> None:
    saved.signature_user_id = None
    saved.signature_version = None
    saved.signature_png = None
    saved.signature_registered_at = None


def snapshot_png(saved) -> bytes | None:
    blob = getattr(saved, "signature_png", None) if saved is not None else None
    if not blob:
        return None
    return bytes(blob)


def resolve_approval_png(
    db: Session,
    user,
    *,
    request_png_b64: Any = None,
    request_user_id: Any = None,
) -> tuple[bytes, int]:
    """
    يتحقق أن الحساب الحالي هو مالك التوقيع ويعيد (png اللقطة، الإصدار).
    لا يعتمد على الاسم أو الوحدة أو عنوان الجهاز.
    """
    uid = int(getattr(user, "id", 0) or 0)
    if uid <= 0:
        raise JudgeSignatureError(OWNER_MISMATCH_MESSAGE, "owner_mismatch")
    if request_user_id not in (None, "", 0, "0"):
        try:
            claimed = int(request_user_id)
        except (TypeError, ValueError) as exc:
            raise JudgeSignatureError(OWNER_MISMATCH_MESSAGE, "owner_mismatch") from exc
        if claimed != uid:
            raise JudgeSignatureError(OWNER_MISMATCH_MESSAGE, "owner_mismatch")

    incoming: bytes | None = None
    if request_png_b64 not in (None, ""):
        incoming = validate_transparent_signature_png(decode_png_b64(request_png_b64))

    master = get_master(db, uid)
    master_bytes = master_png_bytes(master)
    if incoming is None and not master_bytes:
        raise JudgeSignatureError(NO_SIGNATURE_MESSAGE, "no_signature")
    if incoming is not None and master is None:
        master = ensure_master_from_snapshot(db, uid, incoming, source="tablet")
        master_bytes = master_png_bytes(master)
    if master is None or int(master.user_id) != uid:
        raise JudgeSignatureError(OWNER_MISMATCH_MESSAGE, "owner_mismatch")
    png = incoming if incoming is not None else master_bytes
    if not png:
        raise JudgeSignatureError(NO_SIGNATURE_MESSAGE, "no_signature")
    return png, int(master.version or 1)


def signature_public_meta(row: JudgeElectronicSignature | None) -> dict[str, Any]:
    if row is None or not master_png_bytes(row):
        return {
            "registered": False,
            "status": "unregistered",
            "status_ar": "غير مسجل",
            "version": None,
            "registered_at": None,
            "updated_at": None,
        }
    return {
        "registered": True,
        "status": SIGNATURE_STATUS_REGISTERED,
        "status_ar": "مسجل ومعتمد",
        "version": int(row.version or 1),
        "registered_at": row.registered_at.isoformat() if row.registered_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "source": (row.source or "").strip(),
    }


def registered_user_ids(db: Session) -> set[int]:
    rows = (
        db.query(JudgeElectronicSignature.user_id)
        .filter(JudgeElectronicSignature.png_blob.isnot(None))
        .all()
    )
    return {int(r[0]) for r in rows if r and r[0]}
