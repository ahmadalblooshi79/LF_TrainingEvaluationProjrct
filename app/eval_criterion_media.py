"""توثيق صفوف قوائم التقييم — تخزين صور/فيديو خارج /static."""
from __future__ import annotations

import re
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.config import EVAL_CRITERION_MEDIA_DIR
from app.models import (
    EvaluationCriterionMedia,
    EvaluationListPdfItem,
    ExercisePlannerFlowBundle,
    ExercisePlannerFlowBundleActionEval,
)

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


_UNIT_SEG_RE = re.compile(r"[^A-Za-z0-9_-]+")
_LEGACY_JUDGES_RE = re.compile(r"(^|/)judges/\d+(/|$)", re.IGNORECASE)


def media_unit_path_segment(unit_level_key: str) -> str:
    """مقطع مسار آمن من unit_level_key (المعرّف الفعلي للوحدة في النظام)."""
    return _UNIT_SEG_RE.sub("_", (unit_level_key or "").strip())[:64].strip("._")


def is_legacy_judges_media_relpath(rel: str) -> bool:
    norm = (rel or "").replace("\\", "/").strip()
    return bool(_LEGACY_JUDGES_RE.search(norm))


def new_media_filename(media_kind: str, mime_type: str | None) -> str:
    mk = "video" if (media_kind or "").strip().lower() == "video" else "photo"
    ext = ext_for_mime(mime_type, mk)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    short = uuid.uuid4().hex[:8]
    prefix = "VIDEO" if mk == "video" else "IMG"
    return f"{prefix}_{stamp}_{short}{ext}"


def criterion_media_relpath(
    *,
    exercise_id: int,
    unit_level_key: str,
    list_item_id: int | None,
    bundle_action_eval_id: int | None,
    row_index: int,
    filename: str,
) -> str:
    """مسار نسبي تحت instance/eval_criterion_media — بدون judge_id."""
    unit = media_unit_path_segment(unit_level_key)
    name = Path(filename or "").name
    if not unit or not name or ".." in name:
        raise ValueError(".path")
    if list_item_id is not None:
        list_seg = f"evaluation_lists/{int(list_item_id)}"
    elif bundle_action_eval_id is not None:
        list_seg = f"action_eval_lists/{int(bundle_action_eval_id)}"
    else:
        raise ValueError(".scope")
    return (
        f"uploads/exercises/{int(exercise_id)}/units/{unit}/"
        f"{list_seg}/items/{int(row_index)}/{name}"
    )


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


def unlink_criterion_media_file(rel: str) -> None:
    """حذف ملف واحد، ثم مجلد العنصر فقط إن أصبح فارغاً."""
    abs_p = criterion_media_absolute_path((rel or "").strip())
    if abs_p is None:
        return
    if abs_p.is_file():
        try:
            abs_p.unlink()
        except OSError:
            pass
    item_dir = abs_p.parent
    if (
        item_dir.is_dir()
        and item_dir.parent.name == "items"
        and not any(item_dir.iterdir())
    ):
        try:
            item_dir.rmdir()
        except OSError:
            pass


def resolve_media_ownership(
    db: Session, row: EvaluationCriterionMedia
) -> tuple[str, int | None, int | None, int] | None:
    """(unit_level_key, list_item_id, bundle_action_eval_id, row_index) أو None إن نقصت بيانات مؤكدة."""
    uk = (row.unit_level_key or "").strip()
    li = row.evaluation_list_item_id
    ba = row.bundle_action_eval_id
    try:
        ri = int(row.row_index or 0)
    except (TypeError, ValueError):
        return None
    if li is not None:
        li = int(li)
    if ba is not None:
        ba = int(ba)
    if li is None and ba is None:
        return None
    if not uk and li is not None:
        item = db.get(EvaluationListPdfItem, li)
        if item is not None:
            uk = (item.unit_level_key or "").strip()
    if not uk and ba is not None:
        slot = db.get(ExercisePlannerFlowBundleActionEval, ba)
        if slot is not None:
            bundle = db.get(ExercisePlannerFlowBundle, int(slot.bundle_id))
            if bundle is not None:
                uk = (bundle.unit_level_key or "").strip()
    if not media_unit_path_segment(uk):
        return None
    return (uk, li, ba, ri)


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
    if list_item_id is None and bundle_action_eval_id is None:
        raise ValueError(".scope")
    _ensure_free_space(len(bin_data))

    EVAL_CRITERION_MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    fname = new_media_filename(mk, mime)
    rel = criterion_media_relpath(
        exercise_id=int(exercise_id),
        unit_level_key=unit_level_key,
        list_item_id=list_item_id,
        bundle_action_eval_id=bundle_action_eval_id,
        row_index=int(row_index),
        filename=fname,
    )

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
    if list_item_id is None and bundle_action_eval_id is None:
        raise ValueError(".scope")

    src = Path(source_path)
    if not src.is_file():
        raise ValueError(".source")
    size = src.stat().st_size
    _ensure_free_space(size)

    rel = (relpath or "").replace("\\", "/").lstrip("/")
    if not rel or ".." in rel or is_legacy_judges_media_relpath(rel):
        rel = criterion_media_relpath(
            exercise_id=int(exercise_id),
            unit_level_key=unit_level_key,
            list_item_id=list_item_id,
            bundle_action_eval_id=bundle_action_eval_id,
            row_index=int(row_index),
            filename=new_media_filename(mk, mime),
        )

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
        file_relpath=rel.replace("\\", "/"),
        uploaded_by_id=uploaded_by_id,
        client_op_id=(client_op_id or "")[:120],
    )
    db.add(row)
    db.flush()
    return row


def migrate_legacy_judge_media_records(db: Session) -> dict[str, Any]:
    """نقل ملفات judges/ إلى هيكل الوحدات عند اكتمال المعرّفات — دون تخمين."""
    rows = db.query(EvaluationCriterionMedia).order_by(EvaluationCriterionMedia.id).all()
    report: dict[str, Any] = {
        "total_old_files": 0,
        "migrated": 0,
        "left_legacy": 0,
        "already_new": 0,
        "missing_disk": 0,
        "broken_paths": [],
        "left_ids": [],
        "migrated_ids": [],
    }
    for row in rows:
        rel = (row.file_relpath or "").replace("\\", "/").strip()
        if not rel:
            report["broken_paths"].append(int(row.id))
            continue
        if not is_legacy_judges_media_relpath(rel):
            report["already_new"] += 1
            abs_cur = criterion_media_absolute_path(rel)
            if abs_cur is None or not abs_cur.is_file():
                report["missing_disk"] += 1
                report["broken_paths"].append(int(row.id))
            continue
        report["total_old_files"] += 1
        src = criterion_media_absolute_path(rel)
        if src is None or not src.is_file():
            report["missing_disk"] += 1
            report["broken_paths"].append(int(row.id))
            report["left_legacy"] += 1
            report["left_ids"].append(int(row.id))
            continue
        owned = resolve_media_ownership(db, row)
        if owned is None:
            report["left_legacy"] += 1
            report["left_ids"].append(int(row.id))
            continue
        uk, li, ba, ri = owned
        dest_rel = criterion_media_relpath(
            exercise_id=int(row.exercise_id),
            unit_level_key=uk,
            list_item_id=li,
            bundle_action_eval_id=ba,
            row_index=ri,
            filename=src.name,
        )
        dest = criterion_media_absolute_path(dest_rel)
        if dest is None:
            report["left_legacy"] += 1
            report["left_ids"].append(int(row.id))
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.resolve() != src.resolve():
            if dest.exists():
                dest = dest.with_name(f"{dest.stem}_{int(row.id)}{dest.suffix}")
                dest_rel = dest.relative_to(EVAL_CRITERION_MEDIA_DIR.resolve()).as_posix()
            shutil.move(str(src), str(dest))
        row.file_relpath = dest_rel.replace("\\", "/")
        if not (row.unit_level_key or "").strip():
            row.unit_level_key = uk[:64]
        report["migrated"] += 1
        report["migrated_ids"].append(int(row.id))
    db.flush()
    _cleanup_empty_judges_dirs()
    return report


def _cleanup_empty_judges_dirs() -> None:
    """حذف مجلدات judges الفارغة فقط بعد النقل — لا يمس ملفات متبقية."""
    root = EVAL_CRITERION_MEDIA_DIR / "uploads" / "exercises"
    if not root.is_dir():
        return
    for judges_dir in root.glob("*/judges"):
        _rm_empty_dirs_bottom_up(judges_dir)


def _rm_empty_dirs_bottom_up(path: Path) -> None:
    if not path.is_dir():
        return
    for child in list(path.iterdir()):
        if child.is_dir():
            _rm_empty_dirs_bottom_up(child)
    try:
        if path.is_dir() and not any(path.iterdir()):
            path.rmdir()
    except OSError:
        pass
