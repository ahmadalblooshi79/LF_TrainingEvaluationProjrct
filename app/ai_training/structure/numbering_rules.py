"""قواعد الترقيم العسكري — Configuration-driven patterns."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.ai_training.structure_constants import (
    NUM_ARABIC_DOT,
    NUM_ARABIC_LETTER_DOT,
    NUM_LETTER_PAREN,
    NUM_NONE,
    NUM_NUMBER_CLOSE,
    NUM_NUMBER_PAREN,
    NUM_OTHER,
)

# Arabic letters commonly used in military numbering (أ–ي without hamza variants mixed)
_AR_LETTERS = "ابتثجحخدذرزسشصضطظعغفقكلمنهويأإآؤئءة"


@dataclass(frozen=True)
class NumberingMatch:
    numbering_text: str
    numbering_style: str
    numbering_level: int
    remainder: str
    confidence: float
    evidence: tuple[str, ...]


# Order matters: more specific first
_PATTERNS: list[tuple[str, str, int, float, str]] = [
    # (regex, style, level, confidence, evidence_label)
    (rf"^\s*([{_AR_LETTERS}])\s*[\.．、]\s+", NUM_ARABIC_LETTER_DOT, 2, 0.92, "pattern arabic_letter_dot"),
    (rf"^\s*\(\s*([{_AR_LETTERS}])\s*\)\s+", NUM_LETTER_PAREN, 4, 0.92, "pattern letter_parentheses"),
    (r"^\s*\(\s*(\d+)\s*\)\s+", NUM_NUMBER_PAREN, 3, 0.92, "pattern number_parentheses"),
    (r"^\s*(\d+)\s*\)\s+", NUM_NUMBER_CLOSE, 5, 0.85, "pattern number_close_paren"),
    (r"^\s*(\d+)\s*[\.．]\s+", NUM_ARABIC_DOT, 1, 0.93, "pattern arabic_dot"),
    (r"^\s*([a-zA-Z])\s*[\.．]\s+", NUM_ARABIC_LETTER_DOT, 2, 0.7, "pattern latin_letter_dot"),
]


def detect_numbering(text: str | None) -> NumberingMatch | None:
    raw = text or ""
    if not raw.strip():
        return None
    for pattern, style, level, conf, label in _PATTERNS:
        m = re.match(pattern, raw)
        if not m:
            continue
        num_token = m.group(0).strip()
        # Normalize token to canonical form from groups
        if style == NUM_ARABIC_DOT:
            num_token = f"{m.group(1)}."
        elif style == NUM_ARABIC_LETTER_DOT:
            num_token = f"{m.group(1)}."
        elif style == NUM_NUMBER_PAREN:
            num_token = f"({m.group(1)})"
        elif style == NUM_LETTER_PAREN:
            num_token = f"({m.group(1)})"
        elif style == NUM_NUMBER_CLOSE:
            num_token = f"{m.group(1)})"
        remainder = raw[m.end() :].strip()
        return NumberingMatch(
            numbering_text=num_token,
            numbering_style=style,
            numbering_level=level,
            remainder=remainder,
            confidence=conf,
            evidence=(label, f"matched={num_token}"),
        )
    return None


def style_level_hint(style_name: str | None) -> tuple[int | None, list[str]]:
    s = (style_name or "").strip().lower()
    if not s:
        return None, []
    evidence: list[str] = []
    if s.startswith("heading"):
        digits = "".join(ch for ch in s if ch.isdigit())
        level = int(digits) if digits else 1
        evidence.append(f"docx_style={style_name}")
        return min(max(level, 1), 9), evidence
    if "title" in s:
        evidence.append(f"docx_style={style_name}")
        return 1, evidence
    if s.startswith("list"):
        evidence.append(f"docx_style={style_name}")
        return None, evidence
    return None, []


def classify_confidence_band(confidence: float | None, *, high: float, medium: float) -> str:
    if confidence is None:
        return "unknown"
    if confidence >= high:
        return "high"
    if confidence >= medium:
        return "medium"
    return "low"


def numbering_rules_config() -> dict[str, Any]:
    return {
        "patterns": [
            {"style": style, "level": level, "confidence": conf, "label": label}
            for _, style, level, conf, label in _PATTERNS
        ],
        "none": NUM_NONE,
        "other": NUM_OTHER,
    }
