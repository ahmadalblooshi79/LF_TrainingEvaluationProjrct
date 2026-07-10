"""تنسيق نصوص الفكرة العامة/الخاصة كفقرات مرقّمة."""

from __future__ import annotations

import re

_BLANK_SPLIT_RE = re.compile(r"\n\s*\n+")


def split_idea_paragraphs(text: str) -> list[str]:
    """تقسيم النص إلى فقرات (فارغة بين الفقرات أو سطر جديد لكل فقرة)."""
    raw = (text or "").strip()
    if not raw:
        return []
    chunks = [c.strip() for c in _BLANK_SPLIT_RE.split(raw) if c.strip()]
    if len(chunks) > 1:
        return chunks
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    return lines if lines else chunks


def join_idea_paragraphs(paragraphs: list[str]) -> str:
    parts = [(p or "").strip() for p in paragraphs if (p or "").strip()]
    return "\n\n".join(parts)
