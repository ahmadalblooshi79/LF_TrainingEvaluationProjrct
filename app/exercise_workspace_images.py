"""صور تبويبي البرنامج والخريطة في صفحة معلومات التمرين."""
from __future__ import annotations

from pathlib import Path

from flask import abort, send_file

from app.config import EXERCISE_WORKSPACE_IMAGE_DIR

WORKSPACE_IMAGE_KINDS = ("program", "map")
_MAX_BYTES = 12 * 1024 * 1024
_PNG = b"\x89PNG\r\n\x1a\n"
_JPEG = b"\xff\xd8"


def _kind_ok(kind: str) -> str:
    k = (kind or "").strip().lower()
    if k not in WORKSPACE_IMAGE_KINDS:
        abort(404)
    return k


def _ext_from_bytes(data: bytes, filename: str) -> str | None:
    name = (filename or "").strip().lower()
    if data.startswith(_PNG) or name.endswith(".png"):
        if data.startswith(_PNG):
            return ".png"
        return None
    if data.startswith(_JPEG) or name.endswith((".jpg", ".jpeg")):
        if data.startswith(_JPEG):
            return ".jpg"
        return None
    return None


def workspace_image_dir(exercise_id: int) -> Path:
    root = EXERCISE_WORKSPACE_IMAGE_DIR.resolve()
    root.mkdir(parents=True, exist_ok=True)
    out = (root / str(int(exercise_id))).resolve()
    out.relative_to(root)
    out.mkdir(parents=True, exist_ok=True)
    return out


def workspace_image_abspath(relpath: str | None) -> Path | None:
    raw = (relpath or "").replace("\\", "/").strip()
    if not raw or ".." in raw.split("/"):
        return None
    root = EXERCISE_WORKSPACE_IMAGE_DIR.resolve()
    path = (root / raw).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        return None
    return path if path.is_file() else None


def relpath_for(exercise_id: int, kind: str, ext: str) -> str:
    return f"{int(exercise_id)}/{_kind_ok(kind)}{ext}"


def save_workspace_image(
    exercise_id: int, kind: str, filename: str, data: bytes
) -> str:
    k = _kind_ok(kind)
    if not data or len(data) > _MAX_BYTES:
        raise ValueError("حجم الصورة غير مقبول.")
    ext = _ext_from_bytes(data, filename)
    if not ext:
        raise ValueError("يُقبل ملف PNG أو JPG فقط.")
    folder = workspace_image_dir(exercise_id)
    for old in folder.glob(f"{k}.*"):
        try:
            old.unlink()
        except OSError:
            pass
    dest = folder / f"{k}{ext}"
    dest.write_bytes(data)
    return relpath_for(exercise_id, k, ext)


def delete_workspace_image(relpath: str | None) -> None:
    path = workspace_image_abspath(relpath)
    if path is None:
        return
    try:
        path.unlink()
    except OSError:
        pass


def send_workspace_image(relpath: str | None, *, download_name: str):
    path = workspace_image_abspath(relpath)
    if path is None:
        abort(404)
    mt = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    return send_file(
        path,
        mimetype=mt,
        as_attachment=False,
        download_name=download_name or path.name,
        max_age=60,
    )
