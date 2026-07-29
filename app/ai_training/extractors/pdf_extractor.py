"""مستخرج PDF عبر pypdf (بدون OCR)."""

from __future__ import annotations

from pathlib import Path

from app.ai_training.constants import EXT_OCR_REQUIRED, EXT_PARTIAL_SUCCESS, EXT_SUCCESS
from app.ai_training.extractors.base import (
    BaseDocumentExtractor,
    ExtractedBlock,
    ExtractedPage,
    ExtractionResult,
)
from app.ai_training.services.cleaning import clean_text_conservative


class PdfExtractor(BaseDocumentExtractor):
    file_kind = "pdf"

    @classmethod
    def supports(cls, file_type: str) -> bool:
        return (file_type or "").lower().lstrip(".") in ("pdf",)

    def extract(self, path: Path) -> ExtractionResult:
        self.validate_file(path)
        from app.ai_report_library.services.pdf_parser import parse_pdf

        parsed = parse_pdf(path)
        warnings: list[str] = []
        if parsed.warning:
            warnings.append(parsed.warning)

        pages: list[ExtractedPage] = []
        blocks: list[ExtractedBlock] = []
        idx = 0
        for i, raw in enumerate(parsed.pages, start=1):
            cleaned = clean_text_conservative(raw or "")
            pages.append(
                ExtractedPage(
                    page_number=i,
                    page_label=str(i),
                    raw_text=raw or "",
                    cleaned_text=cleaned,
                    extraction_method="pypdf",
                    confidence=0.2 if not cleaned.strip() else 0.85,
                    metadata={},
                )
            )
            for line in (raw or "").split("\n"):
                t = line.strip()
                if not t:
                    continue
                blocks.append(
                    ExtractedBlock(
                        block_index=idx,
                        block_type="paragraph",
                        text_content=clean_text_conservative(t),
                        original_text=t,
                        page_number=i,
                        source_reference=f"pdf:page={i}:line={idx}",
                        extraction_confidence=0.8,
                    )
                )
                idx += 1

        char_count = sum(len(p.cleaned_text or "") for p in pages)
        if parsed.needs_ocr:
            return ExtractionResult(
                success=True,
                status=EXT_OCR_REQUIRED,
                pages=pages,
                blocks=blocks,
                warnings=warnings
                + [
                    "الوثيقة تبدو ممسوحة ضوئياً وتحتاج OCR في مرحلة لاحقة.",
                ],
                metadata={"extractor": "PdfExtractor", "needs_ocr": True, "page_mapping_accuracy": "exact"},
                page_count=parsed.page_count,
                paragraph_count=len(blocks),
                table_count=0,
                character_count=char_count,
            )

        status = EXT_SUCCESS if blocks else EXT_PARTIAL_SUCCESS
        if not blocks:
            warnings.append("لم يُستخرج نص من PDF.")
        return ExtractionResult(
            success=bool(blocks),
            status=status,
            pages=pages,
            blocks=blocks,
            warnings=warnings,
            metadata={"extractor": "PdfExtractor", "needs_ocr": False, "page_mapping_accuracy": "exact"},
            page_count=parsed.page_count,
            paragraph_count=len(blocks),
            table_count=0,
            character_count=char_count,
        )
