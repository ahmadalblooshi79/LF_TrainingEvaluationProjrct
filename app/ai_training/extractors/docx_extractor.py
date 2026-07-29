"""مستخرج DOCX عبر python-docx."""

from __future__ import annotations

from pathlib import Path

from app.ai_training.constants import EXT_PARTIAL_SUCCESS, EXT_SUCCESS
from app.ai_training.extractors.base import (
    BaseDocumentExtractor,
    ExtractedBlock,
    ExtractedPage,
    ExtractionResult,
)
from app.ai_training.services.cleaning import clean_text_conservative


class DocxExtractor(BaseDocumentExtractor):
    file_kind = "docx"

    @classmethod
    def supports(cls, file_type: str) -> bool:
        return (file_type or "").lower().lstrip(".") in ("docx",)

    def extract(self, path: Path) -> ExtractionResult:
        self.validate_file(path)
        from app.ai_report_library.services.docx_parser import parse_docx
        from app.ai_training import config as cfg

        elements = parse_docx(path)
        warnings: list[str] = [
            "DOCX لا يوفر حدود صفحات دقيقة دائماً — page_number قد يكون فارغاً.",
        ]
        blocks: list[ExtractedBlock] = []
        table_count = 0
        full_parts: list[str] = []
        idx = 0
        for el in elements:
            et = el.element_type
            if et == "list_item":
                btype = "list"
            elif et == "heading":
                btype = "heading"
            elif et == "table":
                btype = "table"
                table_count += 1
            else:
                btype = "paragraph"
            if btype == "table" and not cfg.AI_INGESTION_EXTRACT_TABLES:
                continue
            original = el.text or ""
            cleaned = clean_text_conservative(original)
            if not cleaned and btype != "table":
                continue
            table_data = None
            if btype == "table":
                table_data = {"headers": el.headers, "rows": el.rows}
            blocks.append(
                ExtractedBlock(
                    block_index=idx,
                    block_type=btype,
                    text_content=cleaned,
                    original_text=original,
                    page_number=None,
                    style_name=el.style or None,
                    heading_level=el.heading_level,
                    table_data=table_data,
                    source_reference=f"docx:order={el.order}",
                    extraction_confidence=0.9,
                )
            )
            full_parts.append(cleaned)
            idx += 1

        full_text = "\n\n".join(p for p in full_parts if p)
        page = ExtractedPage(
            page_number=None,
            page_label="logical-1",
            raw_text=full_text,
            cleaned_text=clean_text_conservative(full_text),
            extraction_method="python-docx",
            confidence=0.85,
            metadata={"page_mapping_accuracy": "none"},
        )
        status = EXT_SUCCESS if blocks else EXT_PARTIAL_SUCCESS
        if not blocks:
            warnings.append("لم يُستخرج أي Block من ملف DOCX.")
        return ExtractionResult(
            success=bool(blocks),
            status=status,
            pages=[page],
            blocks=blocks,
            warnings=warnings,
            metadata={
                "extractor": "DocxExtractor",
                "page_mapping_accuracy": "none",
                "headers_footers": bool(cfg.AI_INGESTION_EXTRACT_HEADERS_FOOTERS),
            },
            page_count=1,
            paragraph_count=sum(1 for b in blocks if b.block_type in ("paragraph", "heading", "list")),
            table_count=table_count,
            character_count=len(full_text),
        )
