"""توثيق صفوف قوائم التقييم — تخزين صور/فيديو خارج /static."""
from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.config import EVAL_CRITERION_MEDIA_DIR
from app.models import EvaluationCriterionMedia

ALLOWED_PHOTO_TYPES = frozenset(
    {
        "image/jpeg",
        "image/jpg",
        "image/webp",
        "image/png",
        "image/heic",
        "image/heif",
    }
)
ALLOWED_VIDEO_TYPES = frozenset(
    {
        "video/webm",
        "video/mp4",
        "video/quicktime",
        "video/mpeg",
        "video/3gpp",
        "video/3gpp2",
        "video/x-m4v",
    }
)
# لا حد اصطناعي صلب — التحقق بالمساحة الحرة فقط عند المسارات الجديدة
MAX_PHOTO_BYTES = None  # type: ignore[assignment]
MAX_VIDEO_BYTES = None  # type: ignore[assignment]
SERVER_FREE_MARGIN = 50 * 1024 * 1024


def mime_base(mime_type: str | None) -> str:
    raw = (mime_type or "").strip()
    return raw.split(";")[0].strip().lower()


def ext_for_mime(mime_type: str | None, media_kind: str) -> str:
    m = mime_base(mime_type)
    if m in ("image/jpeg", "image/jpg"):
        return ".jpg"
    if m == "image/webp":
        return ".webp"
    if m == "image/png":
        return ".png"
    if m in ("image/heic", "image/heif"):
        return ".heic"
    if m in ("video/webm",):
        return ".webm"
    if m in ("video/mp4", "video/x-m4v"):
        return ".mp4"
    if m == "video/quicktime":
        return ".mov"
    if m == "video/mpeg":
        return ".mpg"
    if m in ("video/3gpp", "video/3gpp2"):
        return ".3gp"
    return ".jpg" if (media_kind or "") == "photo" else ".mp4"


def criterion_media_absolute_path(rel: str) -> Path | None:
    if not rel or ".." in rel.replace("\\", "/"):
        return None
    root = EVAL_CRITERION_MEDIA_DIR.resolve()
    full = (root / rel.strip().replace("\\", "/")).resolve()
    try:
        full.relative_to(root)
    except ValueError:
        return None
    return full


def group_media_rows(
    db: Session,
    exercise_id: int,
    *,
    list_item_id: int | None = None,
    bundle_action_eval_id: int | None = None,
) -> dict[int, list[dict[str, Any]]]:
    q = db.query(EvaluationCriterionMedia).filter(
        EvaluationCriterionMedia.exercise_id == int(exercise_id)
    )
    if list_item_id is not None:
        q = q.filter(
            EvaluationCriterionMedia.evaluation_list_item_id == int(list_item_id),
            EvaluationCriterionMedia.bundle_action_eval_id.is_(None),
        )
    elif bundle_action_eval_id is not None:
        q = q.filter(
            EvaluationCriterionMedia.bundle_action_eval_id == int(bundle_action_eval_id),
            EvaluationCriterionMedia.evaluation_list_item_id.is_(None),
        )
    else:
        return {}
    rows = q.order_by(EvaluationCriterionMedia.row_index, EvaluationCriterionMedia.id).all()
    out: dict[int, list[dict[str, Any]]] = {}
    for r in rows:
        out.setdefault(int(r.row_index), []).append(
            {
                "id": int(r.id),
                "media_kind": (r.media_kind or "photo").strip(),
                "mime_type": mime_base(getattr(r, "mime_type", None)),
            }
        )
    return out


def _ensure_free_space(needed: int) -> None:
    EVAL_CRITERION_MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(str(EVAL_CRITERION_MEDIA_DIR)).free
    if free < needed + SERVER_FREE_MARGIN:
        raise ValueError(".storage")


def persist_criterion_medium(
    db: Session,
    *,
    exercise_id: int,
    unit_level_key: str,
    list_item_id: int | None,
    bundle_action_eval_id: int | None,
    row_index: int,
    media_kind: str,
    mime_type_in: str,
    bin_data: bytes,
    uploaded_by_id: int | None,
    client_op_id: str = "",
) -> EvaluationCriterionMedia:
    """مسار الويب القديم — يكتب من bytes (ملفات صغيرة/متوسطة)."""
    mk = "video" if (media_kind or "").strip().lower() == "video" else "photo"
    mime = mime_base(mime_type_in)
    allowed = ALLOWED_VIDEO_TYPES if mk == "video" else ALLOWED_PHOTO_TYPES
    if mime not in allowed:
        raise ValueError(".mime")
    _ensure_free_space(len(bin_data))

    EVAL_CRITERION_MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    ext = ext_for_mime(mime, mk)
    uid = uuid.uuid4().hex
    if list_item_id is not None:
        folder = f"{int(exercise_id)}/li{int(list_item_id)}/r{int(row_index)}"
        rel = f"{folder}/{uid}{ext}"
    elif bundle_action_eval_id is not None:
        folder = f"{int(exercise_id)}/ba{int(bundle_action_eval_id)}/r{int(row_index)}"
        rel = f"{folder}/{uid}{ext}"
    else:
        raise ValueError(".scope")

    abspath = (EVAL_CRITERION_MEDIA_DIR / rel).resolve()
    root = EVAL_CRITERION_MEDIA_DIR.resolve()
    try:
        abspath.relative_to(root)
    except ValueError:
        raise ValueError(".path")

    abspath.parent.mkdir(parents=True, exist_ok=True)
    abspath.write_bytes(bin_data)

    row = EvaluationCriterionMedia(
        exercise_id=int(exercise_id),
        unit_level_key=(unit_level_key or "")[:64],
        evaluation_list_item_id=list_item_id,
        bundle_action_eval_id=bundle_action_eval_id,
        row_index=int(row_index),
        media_kind=mk,
        mime_type=mime[:120],
        file_relpath=rel.replace("\\", "/"),
        uploaded_by_id=uploaded_by_id,
        client_op_id=(client_op_id or "")[:120],
    )
    db.add(row)
    db.flush()
    return row


def persist_criterion_medium_from_path(
    db: Session,
    *,
    exercise_id: int,
    unit_level_key: str,
    list_item_id: int | None,
    bundle_action_eval_id: int | None,
    row_index: int,
    media_kind: str,
    mime_type_in: str,
    source_path: Path,
    relpath: str,
    uploaded_by_id: int | None,
    client_op_id: str = "",
    checksum: str = "",
) -> EvaluationCriterionMedia:
    """نسخ من ملف مجمع (streaming) إلى المسار النهائي — بدون تحميل كامل في RAM."""
    mk = "video" if (media_kind or "").strip().lower() == "video" else "photo"
    mime = mime_base(mime_type_in)
    allowed = ALLOWED_VIDEO_TYPES if mk == "video" else ALLOWED_PHOTO_TYPES
    if mime and mime not in allowed:
        raise ValueError(".mime")

    src = Path(source_path)
    if not src.is_file():
        raise ValueError(".source")
    size = src.stat().st_size
    _ensure_free_space(size)

    rel = (relpath or "").replace("\\", "/").lstrip("/")
    if not rel or ".." in rel:
        raise ValueError(".path")

    abspath = (EVAL_CRITERION_MEDIA_DIR / rel).resolve()
    root = EVAL_CRITERION_MEDIA_DIR.resolve()
    try:
        abspath.relative_to(root)
    except ValueError:
        raise ValueError(".path")

    abspath.parent.mkdir(parents=True, exist_ok=True)
    if abspath.exists():
        abspath.unlink()
    shutil.copyfile(str(src), str(abspath))

    # checksum اختياري — يُخزَّن في client_op_id إن لزم؛ العمود الأساسي client_op_id
    _ = checksum

    row = EvaluationCriterionMedia(
        exercise_id=int(exercise_id),
        unit_level_key=(unit_level_key or "")[:64],
        evaluation_list_item_id=list_item_id,
        bundle_action_eval_id=bundle_action_eval_id,
        row_index=int(row_index),
        media_kind=mk,
        mime_type=(mime or "")[:120],
        file_relpath=rel,
        uploaded_by_id=uploaded_by_id,
        client_op_id=(client_op_id or "")[:120],
    )
    db.add(row)
    db.flush()
    return row
