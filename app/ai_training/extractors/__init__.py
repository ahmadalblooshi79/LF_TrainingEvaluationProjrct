"""اختيار المستخرج المناسب."""

from __future__ import annotations

from app.ai_training.exceptions import UnsupportedDocumentTypeError
from app.ai_training.extractors.base import BaseDocumentExtractor
from app.ai_training.extractors.docx_extractor import DocxExtractor
from app.ai_training.extractors.pdf_extractor import PdfExtractor
from app.ai_training.extractors.txt_extractor import TxtExtractor

_EXTRACTORS: list[type[BaseDocumentExtractor]] = [DocxExtractor, PdfExtractor, TxtExtractor]


def get_extractor(file_kind: str) -> BaseDocumentExtractor:
    kind = (file_kind or "").lower().lstrip(".")
    for cls in _EXTRACTORS:
        if cls.supports(kind):
            return cls()
    raise UnsupportedDocumentTypeError(f"لا مستخرج للنوع: {file_kind}")
