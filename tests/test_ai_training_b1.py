"""اختبارات Phase B1 — مركز التدريب والاستيعاب (بدون Ollama)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.ai_agentic import config as ag_config
from app.ai_agentic.migration import seed_system_health_defaults
from app.ai_agentic.models import AiAgent, AiAgentRun, AiAuditLog, AiKnowledgeVersion, AiPromptVersion, AiSystemEvent, AiWorkflowRun
from app.ai_agentic.services.agent_registry_service import AgentRegistryService
from app.ai_local_engine.models import AiSettings
from app.ai_local_engine.services.ai_service import ensure_default_settings
from app.ai_training.constants import DOCUMENT_INGESTION_AGENT_KEY
from app.ai_training.exceptions import (
    DocumentAlreadyApprovedError,
    DocumentTooLargeError,
    UnsupportedDocumentTypeError,
)
from app.ai_training.extractors.docx_extractor import DocxExtractor
from app.ai_training.extractors.pdf_extractor import PdfExtractor
from app.ai_training.extractors.txt_extractor import TxtExtractor
from app.ai_training.migration import seed_ingestion_agent
from app.ai_training.models import (
    AiTrainingDocument,
    AiTrainingDocumentBlock,
    AiTrainingDocumentCorrection,
    AiTrainingDocumentEvent,
    AiTrainingDocumentPage,
    AiTrainingDocumentReview,
)
from app.ai_training.security_upload import sha256_bytes, validate_upload_filename, validate_upload_size
from app.ai_training.services.document_service import DocumentService
from app.ai_training.services.ingestion_service import IngestionService
from app.ai_training.services.review_service import ReviewService
from app.database import Base


def _make_txt(path: Path, text: str = "فقرة أولى.\n\nفقرة ثانية.") -> Path:
    path.write_text(text, encoding="utf-8")
    return path


class TrainingB1Tests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(
            bind=self.engine,
            tables=[
                AiSettings.__table__,
                AiAgent.__table__,
                AiWorkflowRun.__table__,
                AiAgentRun.__table__,
                AiPromptVersion.__table__,
                AiKnowledgeVersion.__table__,
                AiAuditLog.__table__,
                AiSystemEvent.__table__,
                AiTrainingDocument.__table__,
                AiTrainingDocumentPage.__table__,
                AiTrainingDocumentBlock.__table__,
                AiTrainingDocumentReview.__table__,
                AiTrainingDocumentCorrection.__table__,
                AiTrainingDocumentEvent.__table__,
            ],
        )
        Session = sessionmaker(bind=self.engine)
        self.db = Session()
        ensure_default_settings(self.db)
        seed_system_health_defaults(self.db)
        seed_ingestion_agent(self.db)
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        ag_config.AI_ENGINE_MODE = "hybrid"
        ag_config.AI_AGENTIC_ENABLED = True

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        self.tmp.cleanup()

    def test_reject_unsupported_and_size(self):
        with self.assertRaises(UnsupportedDocumentTypeError):
            validate_upload_filename("x.exe")
        with self.assertRaises(DocumentTooLargeError):
            validate_upload_size(200 * 1024 * 1024)

    def test_sha256(self):
        self.assertEqual(len(sha256_bytes(b"abc")), 64)

    def test_upload_txt_and_ingest(self):
        path = _make_txt(self.root / "sample.txt")
        data = path.read_bytes()
        with patch("app.ai_training.services.document_service.document_original_dir") as mock_dir:
            mock_dir.return_value = self.root / "orig"
            (self.root / "orig").mkdir(parents=True, exist_ok=True)
            with patch("app.ai_training.services.document_service.document_extracted_dir") as mock_ex:
                mock_ex.return_value = self.root / "ex"
                (self.root / "ex").mkdir(parents=True, exist_ok=True)
                svc = DocumentService(self.db)
                doc = svc.upload(
                    file_bytes=data,
                    original_filename="sample.txt",
                    title="عينة",
                    document_type="guide",
                    user_id=1,
                )
                self.assertEqual(doc.status, "UPLOADED")
                self.assertTrue(Path(doc.storage_path).is_file())
                # ingest via service directly (deterministic)
                result = IngestionService(self.db).run_extraction(doc.id, user_id=1)
                self.assertTrue(result.success)
                self.db.refresh(doc)
                self.assertEqual(doc.status, "NEEDS_REVIEW")
                blocks = self.db.query(AiTrainingDocumentBlock).filter_by(document_id=doc.id).count()
                self.assertGreater(blocks, 0)
                pages = self.db.query(AiTrainingDocumentPage).filter_by(document_id=doc.id).count()
                self.assertGreater(pages, 0)

    def test_txt_extractor(self):
        p = _make_txt(self.root / "a.txt", "Hello\n\nWorld")
        r = TxtExtractor().extract(p)
        self.assertEqual(r.status, "SUCCESS")
        self.assertGreaterEqual(len(r.blocks), 2)

    def test_pdf_ocr_required_detection(self):
        from app.ai_report_library.services.pdf_parser import PdfParseResult

        fake = PdfParseResult(pages=["", ""], elements=[], page_count=2, word_count=0, needs_ocr=True, warning="ocr")
        (self.root / "x.pdf").write_bytes(b"%PDF-1.4 empty")
        with patch("app.ai_report_library.services.pdf_parser.parse_pdf", return_value=fake):
            r = PdfExtractor().extract(self.root / "x.pdf")
        self.assertEqual(r.status, "OCR_REQUIRED")

    def test_docx_extractor_uses_parser(self):
        from app.ai_report_library.services.docx_parser import DocumentElement

        els = [
            DocumentElement(element_type="heading", text="عنوان", style="Heading 1", heading_level=1, order=0),
            DocumentElement(element_type="paragraph", text="نص", style="Normal", order=1),
            DocumentElement(element_type="table", text="a|b", order=2, headers=["a"], rows=[["b"]]),
        ]
        p = self.root / "d.docx"
        p.write_bytes(b"PK fake")
        with patch("app.ai_report_library.services.docx_parser.parse_docx", return_value=els):
            r = DocxExtractor().extract(p)
        self.assertEqual(r.status, "SUCCESS")
        self.assertGreaterEqual(r.table_count, 1)

    def test_review_and_approve_lock(self):
        path = _make_txt(self.root / "r.txt")
        with patch("app.ai_training.services.document_service.document_original_dir") as mock_dir:
            mock_dir.return_value = self.root / "o2"
            (self.root / "o2").mkdir(exist_ok=True)
            with patch("app.ai_training.services.document_service.document_extracted_dir") as mock_ex:
                mock_ex.return_value = self.root / "e2"
                (self.root / "e2").mkdir(exist_ok=True)
                doc = DocumentService(self.db).upload(
                    file_bytes=path.read_bytes(),
                    original_filename="r.txt",
                    title="مراجعة",
                    user_id=2,
                )
                IngestionService(self.db).run_extraction(doc.id, user_id=2)
                rev = ReviewService(self.db)
                review = rev.start_review(doc.id, user_id=2)
                blocks = rev.list_blocks(doc.id)
                self.assertTrue(blocks)
                rev.save_corrections(
                    doc.id,
                    [
                        {
                            "correction_type": "TEXT_CORRECTION",
                            "block_id": blocks[0].id,
                            "corrected_value": {"text_content": "نص معدّل"},
                        }
                    ],
                    review_id=review.id,
                    user_id=2,
                )
                rev.complete_review(doc.id, review_id=review.id, user_id=2)
                rev.approve_extraction(doc.id, user_id=2)
                self.db.refresh(doc)
                self.assertEqual(doc.approval_status, "APPROVED_EXTRACTION")
                self.assertTrue(doc.review_locked)
                with self.assertRaises(DocumentAlreadyApprovedError):
                    rev.save_corrections(doc.id, [], user_id=2)

    def test_ingestion_agent_registered(self):
        a = AgentRegistryService(self.db).get_agent(DOCUMENT_INGESTION_AGENT_KEY)
        self.assertIsNotNone(a)
        self.assertEqual(a.category, "training")

    def test_workflow_ingest_agent(self):
        path = _make_txt(self.root / "w.txt", "اختبار مسار")
        with patch("app.ai_training.services.document_service.document_original_dir") as mock_dir:
            mock_dir.return_value = self.root / "o3"
            (self.root / "o3").mkdir(exist_ok=True)
            with patch("app.ai_training.services.document_service.document_extracted_dir") as mock_ex:
                mock_ex.return_value = self.root / "e3"
                (self.root / "e3").mkdir(exist_ok=True)
                doc = DocumentService(self.db).upload(
                    file_bytes=path.read_bytes(),
                    original_filename="w.txt",
                    title="WF",
                    user_id=1,
                )
                out = IngestionService(self.db).queue_and_run_workflow(doc.id, user_id=1)
                self.assertIn(out["workflow"]["status"], ("COMPLETED", "COMPLETED_WITH_WARNINGS"))
                self.db.refresh(doc)
                self.assertEqual(doc.status, "NEEDS_REVIEW")
                self.assertIsNotNone(doc.latest_workflow_run_id)

    def test_modes(self):
        self.assertTrue(ag_config.is_legacy_runtime_allowed())
        ag_config.AI_ENGINE_MODE = "agentic"
        self.assertTrue(ag_config.is_agentic_runtime_allowed())
        ag_config.AI_ENGINE_MODE = "hybrid"


if __name__ == "__main__":
    unittest.main()
