"""مستخرج TXT مع اكتشاف الترميز."""

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


def _decode_bytes(data: bytes) -> tuple[str, str]:
    try:
        from charset_normalizer import from_bytes

        best = from_bytes(data).best()
        if best is not None:
            return str(best), (best.encoding or "utf-8")
    except Exception:
        pass
    for enc in ("utf-8", "utf-8-sig", "cp1256", "latin-1"):
        try:
            return data.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace"), "utf-8-replace"


class TxtExtractor(BaseDocumentExtractor):
    file_kind = "txt"

    @classmethod
    def supports(cls, file_type: str) -> bool:
        return (file_type or "").lower().lstrip(".") in ("txt",)

    def extract(self, path: Path) -> ExtractionResult:
        self.validate_file(path)
        data = path.read_bytes()
        text, encoding = _decode_bytes(data)
        cleaned = clean_text_conservative(text)
        paragraphs = [p.strip() for p in cleaned.split("\n\n") if p.strip()]
        if not paragraphs:
            paragraphs = [ln.strip() for ln in cleaned.split("\n") if ln.strip()]

        blocks: list[ExtractedBlock] = []
        for i, p in enumerate(paragraphs):
            blocks.append(
                ExtractedBlock(
                    block_index=i,
                    block_type="paragraph",
                    text_content=p,
                    original_text=p,
                    page_number=1,
                    source_reference=f"txt:para={i}",
                    extraction_confidence=0.95,
                )
            )
        page = ExtractedPage(
            page_number=1,
            page_label="1",
            raw_text=text,
            cleaned_text=cleaned,
            extraction_method="txt",
            confidence=0.95,
            metadata={"encoding": encoding},
        )
        status = EXT_SUCCESS if blocks else EXT_PARTIAL_SUCCESS
        return ExtractionResult(
            success=bool(blocks),
            status=status,
            pages=[page],
            blocks=blocks,
            warnings=[] if blocks else ["ملف نصي فارغ بعد التنظيف."],
            metadata={"extractor": "TxtExtractor", "encoding": encoding},
            page_count=1,
            paragraph_count=len(blocks),
            table_count=0,
            character_count=len(cleaned),
        )
