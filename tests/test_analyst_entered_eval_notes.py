# -*- coding: utf-8 -*-
"""صفحة المحللين: الملاحظات المدخلة حسب التنظيم مع التصدير."""

from __future__ import annotations

import json
import unittest
import zipfile
from io import BytesIO

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.analyst_eval_notes import (
    SOURCE_ACTION,
    SOURCE_ALL,
    SOURCE_EVAL,
    build_entered_eval_notes_report,
    build_notes_docx_bytes,
    build_notes_xlsx_bytes,
    flatten_note_rows,
)
from app.database import Base
from app.models import (
    EvaluationListPdfItem,
    EvaluationListSavedResult,
    Exercise,
    ExercisePlannerFlowBundle,
    ExercisePlannerFlowBundleActionEval,
    PlannerFlowBundleEvalSavedResult,
)


class EnteredEvalNotesReportTests(unittest.TestCase):
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

    def _payload(self, *notes: tuple[str, str]) -> str:
        rows = [{"element": el, "notes": note, "row_kind": "score"} for el, note in notes]
        rows.append({"element": "بدون ملاحظة", "notes": "", "row_kind": "score"})
        rows.append({"element": "قسم", "notes": "تجاهل", "row_kind": "section"})
        return json.dumps({"rows": rows}, ensure_ascii=False)

    def test_groups_by_org_order_and_source(self):
        recon_item = EvaluationListPdfItem(
            exercise_id=1,
            exercise_phase="preparation",
            unit_level_key="ul_recon",
            unit_level_label="",
            sort_order=1,
            text="كمين",
        )
        cmd_item = EvaluationListPdfItem(
            exercise_id=1,
            exercise_phase="preparation",
            unit_level_key="ul_brigade_grp_cmd",
            unit_level_label="",
            sort_order=1,
            text="قيادة",
        )
        self.db.add_all([recon_item, cmd_item])
        self.db.flush()
        self.db.add(
            EvaluationListSavedResult(
                evaluation_item_id=int(recon_item.id),
                exercise_id=1,
                exercise_phase="preparation",
                unit_level_key="ul_recon",
                payload_json=self._payload(("رصد", "تأخر الإبلاغ")),
                total_pct=70.0,
            )
        )
        bundle = ExercisePlannerFlowBundle(
            exercise_id=1,
            exercise_phase="battle_exposure",
            unit_level_key="ul_brigade_grp_cmd",
            unit_level_label="قيادة مجموعة اللواء",
        )
        self.db.add(bundle)
        self.db.flush()
        slot = ExercisePlannerFlowBundleActionEval(
            bundle_id=int(bundle.id),
            slot_index=1,
            title="إنقاذ المصابين — معضلة 1",
            file_relpath="1/ibn_1.xlsx",
        )
        self.db.add(slot)
        self.db.flush()
        self.db.add(
            PlannerFlowBundleEvalSavedResult(
                bundle_action_eval_id=int(slot.id),
                exercise_id=1,
                exercise_phase="battle_exposure",
                unit_level_key="ul_brigade_grp_cmd",
                payload_json=self._payload(("إسعاف", "نقص وسائط")),
                total_pct=80.0,
            )
        )
        self.db.commit()

        ex = self.db.query(Exercise).first()
        report = build_entered_eval_notes_report(self.db, ex)
        units = report["units"]
        self.assertEqual([u["unit_key"] for u in units], ["ul_brigade_grp_cmd", "ul_recon"])
        self.assertEqual(report["eval_count"], 1)
        self.assertEqual(report["action_count"], 1)
        self.assertEqual(report["notes_count"], 2)
        self.assertEqual(units[0]["action_notes"][0]["note"], "نقص وسائط")
        self.assertEqual(units[0]["eval_notes"], [])
        self.assertEqual(units[1]["eval_notes"][0]["note"], "تأخر الإبلاغ")
        self.assertEqual(units[1]["eval_notes"][0]["list_title"], "كمين")

        all_rows = flatten_note_rows(report, source=SOURCE_ALL)
        self.assertEqual(len(all_rows), 2)
        self.assertEqual(all_rows[0]["source"], SOURCE_ACTION)
        self.assertEqual(all_rows[1]["source"], SOURCE_EVAL)
        self.assertEqual(len(flatten_note_rows(report, source=SOURCE_EVAL)), 1)
        self.assertEqual(len(flatten_note_rows(report, source=SOURCE_ACTION)), 1)

        xlsx = build_notes_xlsx_bytes(all_rows, title="جميع الملاحظات")
        self.assertTrue(xlsx.startswith(b"PK"))
        with zipfile.ZipFile(BytesIO(xlsx)) as zf:
            self.assertTrue(any(n.startswith("xl/") for n in zf.namelist()))
        docx = build_notes_docx_bytes(all_rows, title="جميع الملاحظات")
        self.assertTrue(docx.startswith(b"PK"))
        with zipfile.ZipFile(BytesIO(docx)) as zf:
            self.assertIn("word/document.xml", zf.namelist())


if __name__ == "__main__":
    unittest.main()
