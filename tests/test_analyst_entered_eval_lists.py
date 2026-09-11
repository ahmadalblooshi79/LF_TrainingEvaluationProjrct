# -*- coding: utf-8 -*-
"""صفحة المحللين: المهام المدخلة مرتبة حسب تسلسل التنظيم."""

from __future__ import annotations

import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import (
    EvaluationListPdfItem,
    EvaluationListSavedResult,
    Exercise,
)
from app.views import _build_entered_eval_lists_report


class EnteredEvalListsReportTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        self.db.add(Exercise(id=1, code="T1", title="تمرين", owner_id=1))
        self.db.commit()
        import app.unit_levels_catalog as ulc

        self._prev_levels = list(ulc.UNIT_LEVELS)
        ulc.UNIT_LEVELS = [
            {"key": "ul_brigade_grp_cmd", "label": "قيادة مجموعة اللواء"},
            {"key": "ul_recon", "label": "سرية الاستطلاع"},
        ]

    def tearDown(self):
        import app.unit_levels_catalog as ulc

        ulc.UNIT_LEVELS = self._prev_levels
        self.db.close()

    def _add_item(self, *, unit_key: str, title: str, sort_order: int) -> EvaluationListPdfItem:
        it = EvaluationListPdfItem(
            exercise_id=1,
            exercise_phase="preparation",
            unit_level_key=unit_key,
            unit_level_label="",
            sort_order=sort_order,
            text=title,
        )
        self.db.add(it)
        self.db.flush()
        return it

    def _add_saved(
        self,
        item: EvaluationListPdfItem,
        *,
        pct: float,
        grade: str,
        approved: bool,
        payload: str = '{"rows":[]}',
    ) -> None:
        self.db.add(
            EvaluationListSavedResult(
                evaluation_item_id=int(item.id),
                exercise_id=1,
                exercise_phase="preparation",
                unit_level_key=item.unit_level_key,
                payload_json=payload,
                total_pct=pct,
                grade_label=grade,
                is_approved=approved,
            )
        )

    def test_includes_approved_and_unapproved_in_org_order(self):
        recon = self._add_item(unit_key="ul_recon", title="كمين", sort_order=1)
        brigade_b = self._add_item(
            unit_key="ul_brigade_grp_cmd", title="قيادة 2", sort_order=2
        )
        brigade_a = self._add_item(
            unit_key="ul_brigade_grp_cmd", title="قيادة 1", sort_order=1
        )
        empty = self._add_item(unit_key="ul_recon", title="غير مدخلة", sort_order=2)
        self._add_saved(recon, pct=81.0, grade="جيد جدا", approved=True)
        self._add_saved(brigade_b, pct=55.0, grade="راسب", approved=False)
        self._add_saved(brigade_a, pct=92.0, grade="ممتاز", approved=True)
        self.db.commit()

        ex = self.db.query(Exercise).first()
        report = _build_entered_eval_lists_report(self.db, ex)
        titles = [r["item_title"] for r in report["entered_rows"]]
        self.assertEqual(titles, ["قيادة 1", "قيادة 2", "كمين"])
        self.assertNotIn("غير مدخلة", titles)
        self.assertEqual(report["entered_count"], 3)
        self.assertEqual(report["approved_count"], 2)
        self.assertEqual(report["pending_count"], 1)
        self.assertTrue(report["entered_rows"][0]["is_approved"])
        self.assertFalse(report["entered_rows"][1]["is_approved"])
        self.assertEqual(empty.text, "غير مدخلة")

    def test_excludes_saved_without_percent_or_grade(self):
        listed = self._add_item(unit_key="ul_recon", title="لها نتيجة", sort_order=1)
        blank = self._add_item(unit_key="ul_recon", title="بدون نسبة", sort_order=2)
        self._add_saved(listed, pct=70.81, grade="جيد", approved=True)
        self.db.add(
            EvaluationListSavedResult(
                evaluation_item_id=int(blank.id),
                exercise_id=1,
                exercise_phase="preparation",
                unit_level_key=blank.unit_level_key,
                payload_json='{"rows":[{"notes":"حفظ فارغ"}]}',
                total_pct=None,
                grade_label="",
                is_approved=False,
            )
        )
        self.db.commit()
        ex = self.db.query(Exercise).first()
        report = _build_entered_eval_lists_report(self.db, ex)
        titles = [r["item_title"] for r in report["entered_rows"]]
        self.assertEqual(titles, ["لها نتيجة"])
        self.assertNotIn("بدون نسبة", titles)
        self.assertEqual(report["entered_count"], 1)
        self.assertEqual(report["pending_count"], 0)
