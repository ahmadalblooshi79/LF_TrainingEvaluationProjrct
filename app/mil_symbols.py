"""ربط رموز تنظيم المعركة بملفات PNG تحت static/mil-symbols (ديناميكي عبر manifest.json)."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

# مطابقة أسماء الملفات المقترحة لصور المستخدم (PNG في مجلد mil-symbols)
_DEFAULT_REGISTRY: dict[str, str] = {
    "brigade:mech_inf": "Mechanized_Infantry_Brigade.png",
    "battalion:infantry": "Mechanized_Infantry_Battalion.png",
    "battalion:armor": "Armor_Battalion.png",
    "battalion:artillery": "Mechanized_Infantry_Battalion.png",
    "company:infantry": "Mechanized_Infantry_Company.png",
    "company:armor": "Armor_Company.png",
    "company:artillery": "Mechanized_Infantry_Company.png",
    "platoon:infantry": "Mechanized_Infantry_Platoon.png",
    "platoon:armor": "Armor_Platoon.png",
    "squad:armor": "Armor_Squad.png",
    "squad:infantry": "Mechanized_Infantry_Squad.png",
}
_DEFAULT_FILENAME = "Mechanized_Infantry_Company.png"

_SAFE_FILENAME = re.compile(r"^[A-Za-z0-9._-]+$")


def _safe_filename(name: str) -> str | None:
    n = (name or "").strip()
    if not n or "/" in n or "\\" in n or ".." in n:
        return None
    if not _SAFE_FILENAME.match(n):
        return None
    return n


def _mil_symbols_dir() -> Path | None:
    try:
        from flask import current_app

        root = Path(current_app.static_folder) / "mil-symbols"
        if root.is_dir():
            return root
    except RuntimeError:
        pass
    return None


def _load_registry(base: Path) -> tuple[dict[str, str], str]:
    """دمج الافتراضي مع manifest.json إن وُجد."""
    reg: dict[str, str] = dict(_DEFAULT_REGISTRY)
    default_fn = _DEFAULT_FILENAME
    mp = base / "manifest.json"
    if not mp.is_file():
        return reg, default_fn
    try:
        data: Any = json.loads(mp.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return reg, default_fn
    if not isinstance(data, dict):
        return reg, default_fn
    for k, v in data.items():
        if k == "_default":
            if isinstance(v, str) and _safe_filename(v):
                default_fn = v
            continue
        if isinstance(k, str) and k.startswith("_"):
            continue
        if isinstance(k, str) and isinstance(v, str) and _safe_filename(v):
            reg[k] = v
    return reg, default_fn


def resolve_military_symbol_static_path(symbol: dict[str, Any]) -> str | None:
    """
    يعيد مساراً نسبياً تحت static/ (مثل mil-symbols/Foo.png) إن وُجد الملف، وإلا None للرجوع إلى SVG.
    يدعم symbol["image"] = "اسم_ملف.png" لتجاوز المفتاح echelon:branch.
    """
    base = _mil_symbols_dir()
    if base is None:
        return None
    reg, default_fn = _load_registry(base)

    fname: str | None = None
    raw_img = symbol.get("image")
    if isinstance(raw_img, str) and raw_img.strip():
        fname = _safe_filename(raw_img.strip())
    else:
        echelon = (symbol.get("echelon") or "").strip()
        branch = (symbol.get("branch") or "").strip()
        key = f"{echelon}:{branch}"
        fname = _safe_filename(reg.get(key, default_fn) or "")

    if not fname:
        return None
    if not (base / fname).is_file():
        return None
    return f"mil-symbols/{fname}"
