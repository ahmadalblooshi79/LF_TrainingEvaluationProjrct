"""اكتشاف أقسام التقرير بالقواعد أولاً."""

from __future__ import annotations

import re
from typing import Any

from app.ai_report_library.constants import (
    CONFIDENCE_NEEDS_REVIEW,
    SECTION_TITLE_MAP,
)


def _normalize_title(title: str) -> str:
    t = re.sub(r"\s+", " ", (title or "").strip())
    t = t.strip(":-–—•*")
    return t


def classify_section_title(title: str) -> tuple[str, float, str]:
    raw = _normalize_title(title)
    if not raw:
        return "unknown", 0.2, "rules"
    if raw in SECTION_TITLE_MAP:
        return SECTION_TITLE_MAP[raw], 0.95, "rules"
    low = raw.lower()
    for key, stype in SECTION_TITLE_MAP.items():
        if key in raw or key.lower() in low:
            return stype, 0.85, "rules"
    # أنماط عامة
    if "قوة" in raw or "إيجاب" in raw:
        return "strengths", 0.75, "rules"
    if "قصور" in raw or "ضعف" in raw or "سلب" in raw:
        return "weaknesses", 0.75, "rules"
    if "دروس" in raw or "عبر" in raw:
        return "lessons_learned", 0.75, "rules"
    if "توصي" in raw:
        return "recommendations", 0.75, "rules"
    if "مقدم" in raw:
        return "introduction", 0.7, "rules"
    if "خاتم" in raw or "خلاص" in raw:
        return "conclusion", 0.7, "rules"
    return "unknown", 0.4, "rules"


def detect_sections_from_elements(elements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    order = 0
    for el in elements:
        text = (el.get("text") or "").strip()
        if not text:
            continue
        is_heading = el.get("element_type") == "heading" or (
            el.get("heading_level") is not None
        )
        # عناوين قصيرة محتملة في PDF
        if not is_heading and len(text) < 80:
            stype, conf, src = classify_section_title(text)
            if stype != "unknown" and conf >= 0.7:
                is_heading = True
        if is_heading:
            if current:
                sections.append(current)
            stype, conf, src = classify_section_title(text)
            review = "needs_review" if conf < CONFIDENCE_NEEDS_REVIEW else "auto_detected"
            current = {
                "original_title": text,
                "normalized_section_type": stype,
                "section_order": order,
                "original_text": "",
                "confidence_score": conf,
                "detection_source": src,
                "review_status": review,
                "page_start": el.get("page_hint"),
            }
            order += 1
        else:
            if current is None:
                current = {
                    "original_title": "محتوى غير مصنّف",
                    "normalized_section_type": "unknown",
                    "section_order": order,
                    "original_text": "",
                    "confidence_score": 0.5,
                    "detection_source": "rules",
                    "review_status": "needs_review",
                    "page_start": el.get("page_hint"),
                }
                order += 1
            sep = "\n" if current["original_text"] else ""
            current["original_text"] += sep + text
    if current:
        sections.append(current)
    return sections
