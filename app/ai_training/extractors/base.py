"""واجهة Extractor الموحدة."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ExtractedPage:
    page_number: int | None
    page_label: str | None
    raw_text: str
    cleaned_text: str
    extraction_method: str
    confidence: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExtractedBlock:
    block_index: int
    block_type: str
    text_content: str
    original_text: str
    page_number: int | None = None
    style_name: str | None = None
    heading_level: int | None = None
    list_level: int | None = None
    numbering_text: str | None = None
    bounding_box: dict[str, Any] | None = None
    table_data: dict[str, Any] | None = None
    source_reference: str | None = None
    extraction_confidence: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExtractionResult:
    success: bool
    status: str  # SUCCESS | PARTIAL_SUCCESS | FAILED | OCR_REQUIRED
    pages: list[ExtractedPage] = field(default_factory=list)
    blocks: list[ExtractedBlock] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    page_count: int = 0
    paragraph_count: int = 0
    table_count: int = 0
    character_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "status": self.status,
            "pages": [asdict(p) for p in self.pages],
            "blocks": [asdict(b) for b in self.blocks],
            "warnings": self.warnings,
            "errors": self.errors,
            "metadata": self.metadata,
            "page_count": self.page_count,
            "paragraph_count": self.paragraph_count,
            "table_count": self.table_count,
            "character_count": self.character_count,
        }


class BaseDocumentExtractor(ABC):
    file_kind: str = "unknown"

    @classmethod
    @abstractmethod
    def supports(cls, file_type: str) -> bool:
        ...

    def validate_file(self, path: Path) -> None:
        if not path.is_file():
            raise FileNotFoundError(str(path))

    @abstractmethod
    def extract(self, path: Path) -> ExtractionResult:
        ...

    def extract_metadata(self, path: Path) -> dict[str, Any]:
        return {"file_name": path.name, "file_size": path.stat().st_size if path.is_file() else 0}

    def extract_pages(self, path: Path) -> list[ExtractedPage]:
        return self.extract(path).pages

    def extract_blocks(self, path: Path) -> list[ExtractedBlock]:
        return self.extract(path).blocks

    def extract_tables(self, path: Path) -> list[ExtractedBlock]:
        return [b for b in self.extract(path).blocks if b.block_type == "table"]
