"""قراءة PDF نصي — بدون OCR تلقائي."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass
class PdfParseResult:
    pages: list[str]
    elements: list[dict[str, Any]]
    page_count: int
    word_count: int
    needs_ocr: bool
    warning: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_pdf(path: str | Path) -> PdfParseResult:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    pages: list[str] = []
    elements: list[dict[str, Any]] = []
    order = 0
    for i, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        pages.append(text)
        for block in text.split("\n"):
            t = block.strip()
            if not t:
                continue
            elements.append(
                {
                    "element_type": "paragraph",
                    "text": t,
                    "style": "",
                    "heading_level": None,
                    "order": order,
                    "page_hint": i,
                    "parent_heading": None,
                    "table_reference": None,
                    "rows": [],
                    "headers": [],
                }
            )
            order += 1

    full = "\n".join(pages).strip()
    words = len(full.split()) if full else 0
    page_count = len(reader.pages)
    # اكتشاف PDF مصور تقريباً: صفحات بلا نص تقريباً
    needs_ocr = page_count > 0 and words < max(8, page_count * 3)
    warning = None
    if needs_ocr:
        warning = "الملف عبارة عن صور ممسوحة ضوئياً ويحتاج إلى معالجة OCR منفصلة."
    return PdfParseResult(
        pages=pages,
        elements=elements,
        page_count=page_count,
        word_count=words,
        needs_ocr=needs_ocr,
        warning=warning,
    )
