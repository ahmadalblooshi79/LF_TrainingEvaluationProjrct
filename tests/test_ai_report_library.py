"""اختبارات أساسية لمكتبة التقارير — بدون تقارير عسكرية حقيقية."""

from __future__ import annotations

import io
import unittest
import zipfile
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.ai_report_library.models import AIReportSource
from app.ai_report_library.security_upload import (
    ReportUploadError,
    sha256_bytes,
    validate_upload_filename,
)
from app.ai_report_library.services.section_detection_service import classify_section_title
from app.ai_report_library.services.text_cleaning_service import TextCleaningService
from app.ai_report_library.services.unit_detection_service import detect_units_from_elements, normalize_unit_name
from app.ai_report_library.services.finding_extraction_service import split_finding_lines, extract_findings
from app.database import Base
from app.permissions import can_view_ai_reports
from app.models import RoleKey, User
from unittest.mock import MagicMock


def _minimal_docx_bytes(paragraphs: list[str]) -> bytes:
    """DOCX بسيط عبر ZIP/OOXML دون python-docx (للرفع)."""
    # استخدام python-docx إن توفر
    from docx import Document

    buf = io.BytesIO()
    doc = Document()
    for p in paragraphs:
        doc.add_paragraph(p)
    doc.save(buf)
    return buf.getvalue()


class UploadSecurityTests(unittest.TestCase):
    def test_reject_doc_and_exe(self):
        with self.assertRaises(ReportUploadError):
            validate_upload_filename("a.doc")
        with self.assertRaises(ReportUploadError):
            validate_upload_filename("a.exe")

    def test_allow_docx_pdf(self):
        self.assertEqual(validate_upload_filename("x.DOCX"), ".docx")
        self.assertEqual(validate_upload_filename("y.pdf"), ".pdf")

    def test_checksum_stable(self):
        self.assertEqual(sha256_bytes(b"abc"), sha256_bytes(b"abc"))
        self.assertNotEqual(sha256_bytes(b"abc"), sha256_bytes(b"abd"))


class CleaningAndDetectionTests(unittest.TestCase):
    def test_clean_page_numbers(self):
        raw = "مقدمة\nصفحة 3\nنص مهم"
        cleaned = TextCleaningService().clean(raw)
        self.assertNotIn("صفحة 3", cleaned)
        self.assertIn("نص مهم", cleaned)

    def test_section_strength(self):
        stype, conf, _ = classify_section_title("نقاط القوة")
        self.assertEqual(stype, "strengths")
        self.assertGreaterEqual(conf, 0.9)

    def test_unit_normalize(self):
        self.assertIn("الكتيبة", normalize_unit_name("ك1"))

    def test_detect_units(self):
        els = [
            {"element_type": "heading", "text": "اللواء", "heading_level": 1},
            {"element_type": "heading", "text": "الكتيبة الأولى", "heading_level": 2},
        ]
        units = detect_units_from_elements(els)
        self.assertTrue(any(u["unit_level"] == "brigade" for u in units))
        self.assertTrue(any("كتيبة" in u["normalized_unit_name"] for u in units))

    def test_split_findings(self):
        text = "1. نقطة أولى طويلة بما يكفي\n2. نقطة ثانية طويلة بما يكفي"
        parts = split_finding_lines(text)
        self.assertGreaterEqual(len(parts), 2)

    def test_extract_findings_from_section(self):
        sections = [
            {
                "original_title": "نقاط القوة",
                "normalized_section_type": "strengths",
                "original_text": "1. أظهرت الكتيبة الأولى قدرة جيدة على الانتشار ضمن التوقيت المحدد.",
                "cleaned_text": "1. أظهرت الكتيبة الأولى قدرة جيدة على الانتشار ضمن التوقيت المحدد.",
            }
        ]
        units = [
            {
                "original_unit_name": "الكتيبة الأولى",
                "normalized_unit_name": "الكتيبة الأولى",
                "unit_level": "battalion",
                "is_brigade_level": False,
            }
        ]
        findings = extract_findings(sections, [], units)
        self.assertTrue(any(f["finding_type"] == "strength" for f in findings))


class PermissionTests(unittest.TestCase):
    def test_judge_denied(self):
        u = MagicMock(spec=User)
        u.role_key = RoleKey.JUDGE.value
        self.assertFalse(can_view_ai_reports(u))

    def test_admin_allowed(self):
        u = MagicMock(spec=User)
        u.role_key = RoleKey.SYSTEM_ADMIN.value
        self.assertTrue(can_view_ai_reports(u))


class StoreAndProcessSmokeTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(
            bind=engine,
            tables=[
                AIReportSource.__table__,
            ],
        )
        # جداول مرتبطة للمعالجة
        from app.ai_report_library.models import (
            AIReportCorrection,
            AIReportFinding,
            AIReportFindingUnit,
            AIReportProcessingLog,
            AIReportSection,
            AIReportTable,
            AIReportUnit,
        )

        Base.metadata.create_all(
            bind=engine,
            tables=[
                AIReportSection.__table__,
                AIReportTable.__table__,
                AIReportUnit.__table__,
                AIReportFinding.__table__,
                AIReportFindingUnit.__table__,
                AIReportProcessingLog.__table__,
                AIReportCorrection.__table__,
            ],
        )
        self.Session = sessionmaker(bind=engine)
        self.db = self.Session()

    def tearDown(self):
        self.db.close()

    def test_store_docx_and_process(self):
        from app.ai_report_library.services.storage_service import store_new_report
        from app.ai_report_library.services.processing_pipeline import process_report

        raw = _minimal_docx_bytes(
            [
                "المقدمة",
                "هذا تمرين تدريبي.",
                "الكتيبة الأولى",
                "نقاط القوة",
                "1. أظهرت الكتيبة الأولى قدرة جيدة على الانتشار ضمن التوقيت المحدد.",
                "نقاط الضعف",
                "1. لوحظ تأخر في تمرير البلاغات إلى مركز عمليات اللواء.",
            ]
        )
        row = store_new_report(
            self.db,
            file_bytes=raw,
            original_filename="sample.docx",
            meta={"report_title": "تقرير تجريبي", "allow_learning": True},
            user_id=1,
        )
        self.assertEqual(row.processing_status, "uploaded")
        processed = process_report(self.db, row.id, use_qwen=False)
        self.assertIn(processed.processing_status, ("ready", "needs_review"))
        self.assertGreaterEqual(processed.sections_count, 1)

    def test_duplicate_checksum(self):
        from app.ai_report_library.services.storage_service import store_new_report

        raw = _minimal_docx_bytes(["نص"])
        store_new_report(
            self.db,
            file_bytes=raw,
            original_filename="a.docx",
            meta={"report_title": "أ"},
            user_id=1,
        )
        with self.assertRaises(ReportUploadError):
            store_new_report(
                self.db,
                file_bytes=raw,
                original_filename="b.docx",
                meta={"report_title": "ب"},
                user_id=1,
            )


if __name__ == "__main__":
    unittest.main()
