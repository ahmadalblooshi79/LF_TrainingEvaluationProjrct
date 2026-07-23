"""قراءة ملفات DOCX إلى عناصر منظمة."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class DocumentElement:
    element_type: str  # heading|paragraph|list_item|table
    text: str = ""
    style: str = ""
    heading_level: int | None = None
    order: int = 0
    page_hint: int | None = None
    parent_heading: str | None = None
    table_reference: int | None = None
    rows: list[list[str]] = field(default_factory=list)
    headers: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_docx(path: str | Path) -> list[DocumentElement]:
    try:
        from docx import Document
        from docx.enum.text import WD_PARAGRAPH_ALIGNMENT
        from docx.oxml.ns import qn
        from docx.table import Table
        from docx.text.paragraph import Paragraph
    except ImportError as exc:
        raise RuntimeError(
            "مكتبة python-docx غير مثبتة. ثبّتها عبر requirements.txt."
        ) from exc

    doc = Document(str(path))
    elements: list[DocumentElement] = []
    order = 0
    parent_heading: str | None = None
    table_idx = 0

    def iter_block_items(parent):
        body = parent.element.body
        for child in body.iterchildren():
            if child.tag == qn("w:p"):
                yield Paragraph(child, parent)
            elif child.tag == qn("w:tbl"):
                yield Table(child, parent)

    for block in iter_block_items(doc):
        if isinstance(block, Paragraph):
            text = (block.text or "").strip()
            if not text:
                continue
            style_name = ""
            try:
                style_name = (block.style.name or "") if block.style else ""
            except Exception:
                style_name = ""
            level = None
            etype = "paragraph"
            if style_name.lower().startswith("heading"):
                etype = "heading"
                digits = "".join(ch for ch in style_name if ch.isdigit())
                level = int(digits) if digits else 1
                parent_heading = text
            elif style_name.lower().startswith("list"):
                etype = "list_item"
            elements.append(
                DocumentElement(
                    element_type=etype,
                    text=text,
                    style=style_name,
                    heading_level=level,
                    order=order,
                    parent_heading=parent_heading if etype != "heading" else None,
                )
            )
            order += 1
        else:
            headers: list[str] = []
            rows: list[list[str]] = []
            for ri, row in enumerate(block.rows):
                cells = [(c.text or "").strip() for c in row.cells]
                if ri == 0:
                    headers = cells
                else:
                    rows.append(cells)
            table_lines = [headers] + rows if headers else rows
            elements.append(
                DocumentElement(
                    element_type="table",
                    text="\n".join(" | ".join(r) for r in table_lines),
                    order=order,
                    parent_heading=parent_heading,
                    table_reference=table_idx,
                    headers=headers,
                    rows=rows,
                )
            )
            table_idx += 1
            order += 1
    return elements
