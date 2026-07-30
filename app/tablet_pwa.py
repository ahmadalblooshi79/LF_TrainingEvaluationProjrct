# -*- coding: utf-8 -*-
"""خدمة تطبيق تابلت المحكمين كـ PWA من مجلد البناء."""
from __future__ import annotations

from pathlib import Path

from flask import Blueprint, abort, current_app, send_from_directory

bp = Blueprint("tablet_pwa", __name__)

_ROOT = Path(__file__).resolve().parents[1]
_PWA_DIR = _ROOT / "flutter_app" / "build" / "web"
_PWA_DIST = _ROOT / "dist" / "tablet_pwa"


def pwa_root() -> Path:
    """يفضّل dist/tablet_pwa إن وُجد، وإلا مخرجات flutter build web."""
    if (_PWA_DIST / "index.html").is_file():
        return _PWA_DIST
    return _PWA_DIR


@bp.get("/tablet")
@bp.get("/tablet/")
def tablet_pwa_index():
    root = pwa_root()
    index = root / "index.html"
    if not index.is_file():
        abort(
            503,
            description=(
                "PWA غير مبني بعد. شغّل BUILD_PWA.bat ثم أعد تشغيل السيرفر."
            ),
        )
    return send_from_directory(root, "index.html")


@bp.get("/tablet/<path:asset_path>")
def tablet_pwa_assets(asset_path: str):
    root = pwa_root()
    if not root.is_dir():
        abort(404)
    # منع الخروج من المجلد
    target = (root / asset_path).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError:
        abort(404)
    if not target.is_file():
        # SPA fallback
        index = root / "index.html"
        if index.is_file() and not asset_path.startswith("assets/"):
            return send_from_directory(root, "index.html")
        abort(404)
    return send_from_directory(root, asset_path)
