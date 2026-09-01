"""PDF اليوم في التخطيط مستقل عن جدول المجرى."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from app.models import ExercisePlannerFlowBundle
from app.views import (
    _normalize_planner_flow_table_document,
    _planner_flow_day_display_label,
    _planner_flow_day_pdf_relpath,
    _safe_planner_flow_day_id,
    _write_planner_flow_day_pdf,
)


class PlannerFlowDayPdfHelpersTests(unittest.TestCase):
    def test_safe_day_id(self):
        self.assertEqual(_safe_planner_flow_day_id("day-2"), "day-2")
        self.assertEqual(_safe_planner_flow_day_id("day-12"), "day-12")
        self.assertEqual(_safe_planner_flow_day_id("day-1788089510220"), "day-1788089510220")
        self.assertEqual(_safe_planner_flow_day_id("../day-1"), "")
        self.assertEqual(_safe_planner_flow_day_id("day-1/../x"), "")
        self.assertEqual(_safe_planner_flow_day_id(""), "")

    def test_relpath(self):
        self.assertEqual(
            _planner_flow_day_pdf_relpath(7, "day-2"),
            "7/day_pdfs/day-2.pdf",
        )

    def test_label_from_table_or_fallback(self):
        bundle = MagicMock(spec=ExercisePlannerFlowBundle)
        bundle.flow_table_json = json.dumps(
            {
                "version": 2,
                "active_day_id": "day-2",
                "days": [
                    {"id": "day-1", "label": "اليوم/1", "note": "", "rows": []},
                    {"id": "day-2", "label": "اليوم/2", "note": "", "rows": []},
                ],
            },
            ensure_ascii=False,
        )
        self.assertEqual(_planner_flow_day_display_label(bundle, "day-2"), "اليوم/2")
        self.assertEqual(_planner_flow_day_display_label(bundle, "day-9"), "اليوم/9")

    def test_write_pdf_does_not_touch_table_document(self):
        before = {
            "version": 2,
            "active_day_id": "day-2",
            "days": [
                {
                    "id": "day-2",
                    "label": "اليوم/2",
                    "note": "ملاحظة",
                    "phase_key": "battle_exposure",
                    "rows": [{"kind": "row", "time": "08:00"}],
                }
            ],
        }
        after = _normalize_planner_flow_table_document(before)
        self.assertEqual(after["active_day_id"], "day-2")
        day2 = next(d for d in after["days"] if d["id"] == "day-2")
        self.assertEqual(day2["note"], "ملاحظة")
        self.assertEqual(len(day2.get("rows") or []), 1)
        self.assertNotIn("pdf_relpath", day2)

    def test_copy_day_pdfs_between_bundles(self):
        from app.views import _copy_planner_day_pdfs, _write_planner_flow_day_pdf

        with tempfile.TemporaryDirectory() as tmp:
            from unittest.mock import patch

            with patch("app.views._planner_flow_bundle_root", return_value=Path(tmp)):
                self.assertIsNotNone(
                    _write_planner_flow_day_pdf(3, "day-2", b"%PDF-1.4\n")
                )
                n = _copy_planner_day_pdfs(3, 9)
                self.assertEqual(n, 1)
                dest = Path(tmp) / "9" / "day_pdfs" / "day-2.pdf"
                self.assertTrue(dest.is_file())
                self.assertEqual(_copy_planner_day_pdfs(3, 3), 0)

    def test_write_rejects_non_pdf(self):
        with tempfile.TemporaryDirectory() as tmp:
            from unittest.mock import patch

            with patch("app.views._planner_flow_bundle_root", return_value=Path(tmp)):
                self.assertIsNone(_write_planner_flow_day_pdf(1, "day-1", b"not-pdf"))
                rel = _write_planner_flow_day_pdf(1, "day-1", b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
                self.assertEqual(rel, "1/day_pdfs/day-1.pdf")
                self.assertTrue((Path(tmp) / rel).is_file())
                self.assertIsNone(_write_planner_flow_day_pdf(1, "../x", b"%PDF-1.4\n"))


class PlannerFlowDayPdfPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from app import create_app

        cls.app = create_app()
        cls.app.config["TESTING"] = True

    def test_pdf_page_requires_login(self):
        client = self.app.test_client()
        resp = client.get("/planner/create-flow/1/days/day-2/pdf", follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/login", resp.headers.get("Location", ""))

    def test_planner_table_has_pdf_button_and_hides_phase_select(self):
        from flask import render_template

        with self.app.test_request_context():
            html = render_template(
                "partials/planner_action_flow_table.html",
                flow_table_days=[
                    {"id": "day-1", "label": "اليوم/1", "note": "", "rows": []}
                ],
                flow_table_active_day_id="day-1",
                flow_table_rows=[],
                flow_table_active_day_note="",
                readonly_mode=False,
                pf_flow_save_url="/save",
                pf_flow_import_docx_url="/import",
                pf_flow_pull_ibank_url="/ibank",
                pf_flow_distribute_judges_url="/dist",
                pf_flow_enable_day_phase=False,
                pf_flow_day_pdf_url_tpl="/planner/create-flow/1/days/__DAY__/pdf",
            )
        self.assertIn('id="pf-flow-day-pdf-btn"', html)
        self.assertIn("PDF", html)
        self.assertNotIn('id="pf-flow-day-phase"', html)
        self.assertNotIn("مرحلة التمرين لهذا اليوم", html)
        pdf_pos = html.find('id="pf-flow-day-pdf-btn"')
        clear_pos = html.find('id="pf-flow-clear-day-btn"')
        self.assertGreater(clear_pos, pdf_pos)

    def test_docx_bytes_not_converted_when_invalid(self):
        from app.planner_flow_docx_to_pdf import convert_docx_bytes_to_pdf

        self.assertIsNone(convert_docx_bytes_to_pdf(b""))
        self.assertIsNone(convert_docx_bytes_to_pdf(b"not-zip"))

    def test_table_pdf_fallback_builds_pdf(self):
        from app.planner_flow_table_pdf import _HAS_REPORTLAB, build_planner_flow_table_pdf

        if not _HAS_REPORTLAB:
            self.skipTest("reportlab not installed")
        pdf = build_planner_flow_table_pdf(
            day_label="اليوم/2",
            note="تمرين",
            rows=[
                {"kind": "event", "text": "الحدث/1"},
                {
                    "kind": "row",
                    "time": "08:00",
                    "time_kora": "",
                    "time_from": "",
                    "time_to": "",
                    "report_systems": "",
                    "description": "وصف",
                    "assignee": "محكم",
                    "reaction": "",
                    "notes": "",
                },
            ],
        )
        self.assertIsNotNone(pdf)
        self.assertTrue(pdf.startswith(b"%PDF"))

    def test_ibank_table_keeps_phase_select_without_pdf_button(self):
        from flask import render_template

        with self.app.test_request_context():
            html = render_template(
                "partials/planner_action_flow_table.html",
                flow_table_days=[
                    {"id": "day-1", "label": "اليوم/1", "note": "", "rows": []}
                ],
                flow_table_active_day_id="day-1",
                flow_table_rows=[],
                flow_table_active_day_note="",
                readonly_mode=False,
                pf_flow_save_url="/save",
                pf_flow_import_docx_url="/import",
                pf_flow_enable_day_phase=True,
                pf_flow_phase_options=[{"key": "battle_exposure", "label": "مرحلة"}],
            )
        self.assertIn("مرحلة التمرين لهذا اليوم", html)
        self.assertNotIn('id="pf-flow-day-pdf-btn"', html)


if __name__ == "__main__":
    unittest.main()
