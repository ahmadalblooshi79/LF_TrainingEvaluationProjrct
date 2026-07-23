"""اكتشاف وحدات اللواء وهيكلها."""

from __future__ import annotations

import re
from typing import Any

from app.ai_report_library.constants import CONFIDENCE_NEEDS_REVIEW

_UNIT_PATTERNS: list[tuple[re.Pattern[str], str, bool]] = [
    (re.compile(r"^(قيادة\s+)?اللواء\b", re.I), "brigade", True),
    (re.compile(r"مركز\s+عمليات\s+(اللواء)?", re.I), "ops_center", True),
    (re.compile(r"الكتيبة\s*(الأولى|الثانية|الثالثة|الرابعة|\d+|رقم\s*\(?\d+\)?)", re.I), "battalion", False),
    (re.compile(r"\bك\s*(\d+)\b"), "battalion", False),
    (re.compile(r"كتيبة\s+الإسناد", re.I), "support", False),
    (re.compile(r"السرية\s*(الأولى|الثانية|الثالثة|\d+|القيادة|الإشارة)", re.I), "company", False),
    (re.compile(r"الفصيلة", re.I), "platoon", False),
    (re.compile(r"الجماعة", re.I), "squad", False),
]


def _guess_level(name: str) -> tuple[str, bool, float]:
    for pat, level, is_bde in _UNIT_PATTERNS:
        if pat.search(name):
            return level, is_bde or level == "brigade", 0.85
    if "لواء" in name:
        return "brigade", True, 0.7
    if "كتيبة" in name or re.search(r"\bك\d+\b", name):
        return "battalion", False, 0.7
    if "سرية" in name:
        return "company", False, 0.7
    return "other", False, 0.45


def normalize_unit_name(name: str) -> str:
    t = re.sub(r"\s+", " ", (name or "").strip())
    t = t.replace("الكتيبة رقم (", "الكتيبة ").replace(")", "")
    t = re.sub(r"الكتيبة\s*(\d+)", r"الكتيبة \1", t)
    t = re.sub(r"\bك\s*(\d+)\b", r"الكتيبة \1", t)
    # أرقام عربية شائعة
    t = t.replace("الأولى", "1").replace("الثانية", "2").replace("الثالثة", "3").replace("الرابعة", "4")
    t = re.sub(r"الكتيبة\s*1\b", "الكتيبة الأولى", t)
    t = re.sub(r"الكتيبة\s*2\b", "الكتيبة الثانية", t)
    t = re.sub(r"الكتيبة\s*3\b", "الكتيبة الثالثة", t)
    t = re.sub(r"الكتيبة\s*4\b", "الكتيبة الرابعة", t)
    return t.strip()


def detect_units_from_elements(elements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    seen: set[str] = set()
    order = 0
    # دائماً أضف جذر اللواء إن وُجدت أي وحدة
    for el in elements:
        if el.get("element_type") not in ("heading", "paragraph", "list_item"):
            # أسماء صفوف الجداول
            if el.get("element_type") == "table":
                for row in el.get("rows") or []:
                    if row:
                        _maybe_add(row[0], found, seen, order, "table")
                        order = len(found)
            continue
        text = (el.get("text") or "").strip()
        if not text or len(text) > 120:
            continue
        level, is_bde, conf = _guess_level(text)
        if conf < 0.55 and el.get("element_type") != "heading":
            continue
        if conf >= 0.55:
            _maybe_add(text, found, seen, order, "heading" if el.get("element_type") == "heading" else "paragraph")
            order = len(found)
    if found and not any(u["is_brigade_level"] for u in found):
        found.insert(
            0,
            {
                "original_unit_name": "اللواء",
                "normalized_unit_name": "اللواء",
                "unit_level": "brigade",
                "parent_unit_id": None,
                "unit_order": 0,
                "is_brigade_level": True,
                "detection_source": "rules",
                "confidence_score": 0.6,
                "review_status": "needs_review",
            },
        )
        for i, u in enumerate(found):
            u["unit_order"] = i
    return found


def _maybe_add(name: str, found: list, seen: set[str], order: int, source: str) -> None:
    level, is_bde, conf = _guess_level(name)
    if conf < 0.55:
        return
    norm = normalize_unit_name(name)
    key = norm.lower()
    if key in seen:
        return
    seen.add(key)
    review = "needs_review" if conf < CONFIDENCE_NEEDS_REVIEW else "auto_detected"
    found.append(
        {
            "original_unit_name": name.strip(),
            "normalized_unit_name": norm,
            "unit_level": level,
            "parent_unit_id": None,
            "unit_order": order,
            "is_brigade_level": is_bde,
            "detection_source": source,
            "confidence_score": conf,
            "review_status": review,
        }
    )
