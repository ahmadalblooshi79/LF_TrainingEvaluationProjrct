"""تنظيف النص دون إعادة صياغة."""

from __future__ import annotations

import re


_PAGE_RE = re.compile(r"^\s*(صفحة|page)\s*\d+\s*$", re.I | re.M)
_MULTI_SPACE = re.compile(r"[ \t\u00a0]{2,}")
_MULTI_NL = re.compile(r"\n{3,}")
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def clean_text(text: str, *, repeated_headers: list[str] | None = None) -> str:
    if not text:
        return ""
    out = text.replace("\r\n", "\n").replace("\r", "\n")
    out = _CTRL.sub("", out)
    lines = []
    header_set = {h.strip() for h in (repeated_headers or []) if h and h.strip()}
    for line in out.split("\n"):
        s = line.strip()
        if not s:
            lines.append("")
            continue
        if _PAGE_RE.match(s):
            continue
        if s in header_set:
            continue
        lines.append(line.rstrip())
    out = "\n".join(lines)
    out = _MULTI_SPACE.sub(" ", out)
    out = _MULTI_NL.sub("\n\n", out)
    return out.strip()


class TextCleaningService:
    def clean(self, text: str, *, repeated_headers: list[str] | None = None) -> str:
        return clean_text(text, repeated_headers=repeated_headers)
