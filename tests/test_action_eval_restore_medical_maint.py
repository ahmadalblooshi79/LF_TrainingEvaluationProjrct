# -*- coding: utf-8 -*-
"""إظهار نتائج قوائم تقييم المعاضل على اليوم الصحيح دون المساس بالنتائج."""
from __future__ import annotations

import json
import unittest
import zipfile
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.action_eval_ibank_sync import (
    action_eval_storage_relpath,
    build_judge_action_eval_display_groups,
    parse_action_eval_storage_relpath,
    publish_action_eval_lists_from_ibank,
    restore_misplaced_action_eval_day_slots,
)
from app.config import INFO_BANK_DIR, PLANNER_FLOW_BUNDLE_DIR
from app.database import Base
from app.info_bank_tree import flow_day_catalog_key
from app.models import (
    Exercise,
    ExercisePlannerFlowBundle,
    ExercisePlannerFlowBundleActionEval,
    InformationBankEventFlowTable,
    InformationBankTreeNode,
    PlannerFlowBundleEvalSavedResult,
)
from app.models.user import RoleKey, User

DAY2 = "day-1788070146115"
DAY1_TEXT = "تعرض سرية الاستطلاع لكمين"
DAY2_TEXT = "فرض الصمت اللاسلكي على الوحدات"
TITLE = f"إنقاذ المصابين — معضلة 1: {DAY1_TEXT}"
DAY2_TITLE = f"إنقاذ المصابين — معضلة 1: {DAY2_TEXT}"


def _slot_ids(groups: list[dict]) -> list[int]:
    return [
        int(row["slot_id"])
        for g in groups
        for folder in g.get("list_folder_groups") or []
        for row in folder.get("rows") or []
    ]


def _write_minimal_xlsx(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types></Types>')


class RestoreMedicalMaintDayOneTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        self.db.add(
            User(id=1, username="j1", password_hash="x", role_key=RoleKey.JUDGE.value)
        )
        self.db.add(Exercise(id=1, code="T1", title="تمرين", owner_id=1))
        self.db.add(
            InformationBankEventFlowTable(
                flow_table_json=json.dumps(
                    {
                        "version": 2,
                        "active_day_id": "day-1",
                        "days": [
                            {
                                "id": "day-1",
                                "label": "اليوم/1",
                                "rows": [
                                    {
                                        "kind": "dilemma",
                                        "text": f"المعضلة/1: {DAY1_TEXT}",
                                    }
                                ],
                            },
                            {
                                "id": DAY2,
                                "label": "اليوم/2",
                                "rows": [
                                    {
                                        "kind": "dilemma",
                                        "text": f"المعضلة/1: {DAY2_TEXT}",
                                    }
                                ],
                            },
                        ],
                    },
                    ensure_ascii=False,
                )
            )
        )
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def _file_node(self, day_id: str, name: str) -> int:
        node = InformationBankTreeNode(
            kind="action_eval",
            name=name,
            is_folder=False,
            catalog_phase_key=flow_day_catalog_key(day_id),
            sort_order=0,
        )
        self.db.add(node)
        self.db.flush()
        return int(node.id)

    def _bundle_with_pair(self, unit_key: str, title: str) -> tuple[int, int]:
        bundle = ExercisePlannerFlowBundle(
            exercise_id=1,
            exercise_phase="battle_exposure",
            unit_level_key=unit_key,
            unit_level_label=unit_key,
        )
        self.db.add(bundle)
        self.db.flush()
        nid_saved = self._file_node(DAY2, f"{unit_key}-saved.xlsx")
        nid_empty = self._file_node("day-1", f"{unit_key}-empty.xlsx")
        saved_slot = ExercisePlannerFlowBundleActionEval(
            bundle_id=int(bundle.id),
            slot_index=1,
            title=title,
            file_relpath=action_eval_storage_relpath(int(bundle.id), nid_saved),
        )
        empty_slot = ExercisePlannerFlowBundleActionEval(
            bundle_id=int(bundle.id),
            slot_index=2,
            title=title,
            file_relpath=action_eval_storage_relpath(int(bundle.id), nid_empty),
        )
        self.db.add_all([saved_slot, empty_slot])
        self.db.flush()
        self.db.add(
            PlannerFlowBundleEvalSavedResult(
                bundle_action_eval_id=int(saved_slot.id),
                exercise_id=1,
                exercise_phase="battle_exposure",
                unit_level_key=unit_key,
                payload_json=json.dumps(
                    {"rows": [{"row_kind": "score", "max_val": "100", "acquired": "90"}]},
                    ensure_ascii=False,
                ),
                total_pct=90.0,
                is_approved=True,
            )
        )
        self.db.commit()
        return int(saved_slot.id), int(empty_slot.id)

    def test_medical_day_one_shows_saved_slot_not_empty_copy(self):
        saved_id, empty_id = self._bundle_with_pair("ul_medical", TITLE)
        groups, _meta = build_judge_action_eval_display_groups(
            self.db, exercise_id=1, flow_day_id="day-1"
        )
        ids = _slot_ids(groups)
        self.assertIn(saved_id, ids)
        self.assertNotIn(empty_id, ids)

    def test_maint_day_one_shows_saved_slot(self):
        title = f"إنقاذ وإخلاء الآليات — معضلة 1: {DAY1_TEXT}"
        saved_id, empty_id = self._bundle_with_pair("ul_maint", title)
        groups, _meta = build_judge_action_eval_display_groups(
            self.db, exercise_id=1, flow_day_id="day-1"
        )
        ids = _slot_ids(groups)
        self.assertIn(saved_id, ids)
        self.assertNotIn(empty_id, ids)

    def test_other_unit_also_shows_saved_slot(self):
        saved_id, empty_id = self._bundle_with_pair("ul_sig", TITLE)
        groups, _meta = build_judge_action_eval_display_groups(
            self.db, exercise_id=1, flow_day_id="day-1"
        )
        ids = _slot_ids(groups)
        self.assertIn(saved_id, ids)
        self.assertNotIn(empty_id, ids)
        row = (
            self.db.query(PlannerFlowBundleEvalSavedResult)
            .filter(PlannerFlowBundleEvalSavedResult.bundle_action_eval_id == saved_id)
            .one()
        )
        self.assertEqual(int(row.bundle_action_eval_id), saved_id)
        self.assertEqual(row.total_pct, 90.0)
        self.assertTrue(row.is_approved)

    def test_day_two_hides_day_one_titled_list(self):
        saved_id, empty_id = self._bundle_with_pair("ul_medical", TITLE)
        groups, _meta = build_judge_action_eval_display_groups(
            self.db, exercise_id=1, flow_day_id=DAY2
        )
        ids = _slot_ids(groups)
        self.assertNotIn(saved_id, ids)
        self.assertNotIn(empty_id, ids)

    def test_day_two_keeps_real_day_two_list(self):
        bundle = ExercisePlannerFlowBundle(
            exercise_id=1,
            exercise_phase="battle_exposure",
            unit_level_key="ul_medical",
            unit_level_label="ul_medical",
        )
        self.db.add(bundle)
        self.db.flush()
        nid = self._file_node(DAY2, "day2.xlsx")
        slot = ExercisePlannerFlowBundleActionEval(
            bundle_id=int(bundle.id),
            slot_index=1,
            title=DAY2_TITLE,
            file_relpath=action_eval_storage_relpath(int(bundle.id), nid),
        )
        self.db.add(slot)
        self.db.commit()
        groups, _meta = build_judge_action_eval_display_groups(
            self.db, exercise_id=1, flow_day_id=DAY2
        )
        self.assertIn(int(slot.id), _slot_ids(groups))
        groups1, _meta1 = build_judge_action_eval_display_groups(
            self.db, exercise_id=1, flow_day_id="day-1"
        )
        self.assertNotIn(int(slot.id), _slot_ids(groups1))

    def test_restore_relinks_saved_and_deletes_empty(self):
        saved_id, empty_id = self._bundle_with_pair("ul_medical", TITLE)
        saved = self.db.get(ExercisePlannerFlowBundleActionEval, saved_id)
        empty = self.db.get(ExercisePlannerFlowBundleActionEval, empty_id)
        empty_nid = parse_action_eval_storage_relpath(empty.file_relpath)
        for slot in (saved, empty):
            _write_minimal_xlsx(PLANNER_FLOW_BUNDLE_DIR / slot.file_relpath)
        stats = restore_misplaced_action_eval_day_slots(self.db, exercise_id=1)
        self.db.commit()
        self.assertGreaterEqual(int(stats.get("relinked") or 0), 1)
        saved = self.db.get(ExercisePlannerFlowBundleActionEval, saved_id)
        self.assertIsNotNone(saved)
        self.assertEqual(parse_action_eval_storage_relpath(saved.file_relpath), empty_nid)
        self.assertIsNone(self.db.get(ExercisePlannerFlowBundleActionEval, empty_id))
        row = (
            self.db.query(PlannerFlowBundleEvalSavedResult)
            .filter(PlannerFlowBundleEvalSavedResult.bundle_action_eval_id == saved_id)
            .one()
        )
        self.assertEqual(row.total_pct, 90.0)
        self.assertTrue(row.is_approved)

    def test_publish_does_not_overwrite_saved_title(self):
        unit_key = "ul_brigade_grp_cmd"
        day_root = InformationBankTreeNode(
            kind="action_eval",
            name="اليوم/1",
            is_folder=True,
            catalog_phase_key=flow_day_catalog_key("day-1"),
            sort_order=0,
        )
        self.db.add(day_root)
        self.db.flush()
        folder = InformationBankTreeNode(
            kind="action_eval",
            parent_id=int(day_root.id),
            name="قيادة",
            is_folder=True,
            catalog_unit_key=unit_key,
            sort_order=0,
        )
        self.db.add(folder)
        self.db.flush()
        rel = "action_eval/tree/test/restore_saved.xlsx"
        dest = INFO_BANK_DIR / rel
        _write_minimal_xlsx(dest)
        node = InformationBankTreeNode(
            kind="action_eval",
            parent_id=int(folder.id),
            name=f"إنقاذ المصابين — معضلة 1: {DAY1_TEXT}.xlsx",
            is_folder=False,
            catalog_unit_key=unit_key,
            catalog_phase_key=flow_day_catalog_key("day-1"),
            file_relpath=rel.replace("\\", "/"),
            sort_order=0,
        )
        self.db.add(node)
        self.db.flush()
        nid = int(node.id)
        publish_action_eval_lists_from_ibank(
            self.db,
            exercise_id=1,
            phase_key="battle_exposure",
            unit_key=unit_key,
            selected_node_ids={nid},
            flow_day_id="day-1",
        )
        self.db.flush()
        bundle = (
            self.db.query(ExercisePlannerFlowBundle)
            .filter(ExercisePlannerFlowBundle.unit_level_key == unit_key)
            .one()
        )
        slot = (
            self.db.query(ExercisePlannerFlowBundleActionEval)
            .filter(ExercisePlannerFlowBundleActionEval.bundle_id == int(bundle.id))
            .one()
        )
        original = "عنوان محفوظ لا يُستبدل — معضلة 1: " + DAY1_TEXT
        slot.title = original
        self.db.add(
            PlannerFlowBundleEvalSavedResult(
                bundle_action_eval_id=int(slot.id),
                exercise_id=1,
                exercise_phase="battle_exposure",
                unit_level_key=unit_key,
                payload_json="{}",
                total_pct=80.0,
                is_approved=True,
            )
        )
        self.db.commit()
        publish_action_eval_lists_from_ibank(
            self.db,
            exercise_id=1,
            phase_key="battle_exposure",
            unit_key=unit_key,
            selected_node_ids={nid},
            flow_day_id="day-1",
        )
        self.db.flush()
        slot = self.db.get(ExercisePlannerFlowBundleActionEval, int(slot.id))
        self.assertEqual(slot.title, original)


if __name__ == "__main__":
    unittest.main()
