# -*- coding: utf-8 -*-
"""إعادة إظهار قوائم تقييم المعاضل عند اختفاء عقد البنك دون المساس بالنتائج."""

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
    publish_action_eval_lists_from_ibank,
    repair_orphaned_action_eval_slots,
    withdraw_action_eval_for_deleted_ibank_nodes,
)
from app.config import INFO_BANK_DIR, PLANNER_FLOW_BUNDLE_DIR
from app.database import Base
from app.info_bank_tree import (
    ensure_information_bank_kind,
    flow_day_catalog_key,
    invalidate_information_bank_kind_cache,
)
from app.models import (
    Exercise,
    ExercisePlannerFlowBundle,
    ExercisePlannerFlowBundleActionEval,
    InformationBankEventFlowTable,
    InformationBankTreeNode,
    InformationBankUnitLevel,
    PlannerFlowBundleEvalSavedResult,
)


def _write_minimal_xlsx(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types></Types>')


class ActionEvalOrphanRestoreTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        self.unit_key = "ul_brigade_grp_cmd"
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
                                "phase_key": "battle_exposure",
                                "rows": [
                                    {
                                        "kind": "dilemma",
                                        "text": "المعضلة/1: كمين على الاستطلاع",
                                        "assignee": "",
                                    },
                                    {
                                        "kind": "row",
                                        "text": "إجراء",
                                        "assignee": "محكم قيادة مجموعة اللواء",
                                    },
                                ],
                            }
                        ],
                    },
                    ensure_ascii=False,
                )
            )
        )
        self.db.add(Exercise(id=1, code="T1", title="تمرين", owner_id=1))
        self.db.add(
            InformationBankUnitLevel(
                key="ul_brigade_grp_cmd",
                label="قيادة مجموعة اللواء",
                brigade_group="1",
                included_in_exercise=True,
            )
        )
        self.db.commit()
        invalidate_information_bank_kind_cache("action_eval")
        ensure_information_bank_kind(self.db, "action_eval")
        self.old_nid = self._add_file_under_day("day-1", "إجراءات الاستطلاع.xlsx")
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def _add_file_under_day(self, day_id: str, name: str) -> int:
        day_root = (
            self.db.query(InformationBankTreeNode)
            .filter(
                InformationBankTreeNode.kind == "action_eval",
                InformationBankTreeNode.catalog_phase_key
                == flow_day_catalog_key(day_id),
            )
            .first()
        )
        self.assertIsNotNone(day_root)
        folder = InformationBankTreeNode(
            kind="action_eval",
            parent_id=int(day_root.id),
            name="قيادة مجموعة اللواء",
            is_folder=True,
            catalog_unit_key=self.unit_key,
            catalog_phase_key="",
            sort_order=0,
        )
        self.db.add(folder)
        self.db.flush()
        rel = f"action_eval/tree/orphan_restore/{day_id}_{name}"
        dest = INFO_BANK_DIR / rel
        _write_minimal_xlsx(dest)
        node = InformationBankTreeNode(
            kind="action_eval",
            parent_id=int(folder.id),
            name=name,
            is_folder=False,
            catalog_unit_key=self.unit_key,
            catalog_phase_key=flow_day_catalog_key(day_id),
            file_relpath=rel.replace("\\", "/"),
            sort_order=0,
        )
        self.db.add(node)
        self.db.flush()
        return int(node.id)

    def _publish_and_save(self) -> tuple[int, int, str]:
        publish_action_eval_lists_from_ibank(
            self.db,
            exercise_id=1,
            phase_key="preparation",
            unit_key=self.unit_key,
            selected_node_ids={self.old_nid},
            flow_day_id="day-1",
        )
        self.db.flush()
        slot = (
            self.db.query(ExercisePlannerFlowBundleActionEval)
            .filter(
                ExercisePlannerFlowBundleActionEval.file_relpath.like(
                    f"%ibn_{self.old_nid}.xlsx"
                )
            )
            .one()
        )
        slot.title = "إجراءات الاستطلاع — معضلة 1: كمين على الاستطلاع"
        payload = json.dumps({"rows": [{"score": 88}]}, ensure_ascii=False)
        saved = PlannerFlowBundleEvalSavedResult(
            bundle_action_eval_id=int(slot.id),
            exercise_id=1,
            exercise_phase="preparation",
            unit_level_key=self.unit_key,
            payload_json=payload,
            total_pct=88.0,
            grade_label="جيد جداً",
            is_approved=True,
        )
        self.db.add(saved)
        self.db.flush()
        return int(slot.id), int(saved.id), payload

    def _delete_ibank_node(self, nid: int) -> None:
        node = self.db.get(InformationBankTreeNode, int(nid))
        self.assertIsNotNone(node)
        self.db.delete(node)
        self.db.flush()
        self.assertIsNone(self.db.get(InformationBankTreeNode, int(nid)))

    def test_withdraw_deleted_nodes_keeps_slot_and_result(self):
        slot_id, saved_id, payload = self._publish_and_save()
        withdraw_action_eval_for_deleted_ibank_nodes(self.db, {self.old_nid})
        self.db.flush()
        slot = self.db.get(ExercisePlannerFlowBundleActionEval, slot_id)
        saved = self.db.get(PlannerFlowBundleEvalSavedResult, saved_id)
        self.assertIsNotNone(slot)
        self.assertIsNotNone(saved)
        self.assertEqual(saved.payload_json, payload)
        self.assertEqual(saved.total_pct, 88.0)
        self.assertTrue(saved.is_approved)

    def test_orphan_published_list_visible_on_day_one(self):
        slot_id, saved_id, payload = self._publish_and_save()
        self._delete_ibank_node(self.old_nid)
        groups, meta = build_judge_action_eval_display_groups(
            self.db,
            exercise_id=1,
            flow_day_id="day-1",
        )
        self.assertGreater(int(meta.get("published_count") or 0), 0)
        self.assertTrue(groups)
        listed_slot_ids = [
            int(row["slot_id"])
            for g in groups
            for folder in g.get("list_folder_groups") or []
            for row in folder.get("rows") or []
        ]
        self.assertIn(slot_id, listed_slot_ids)
        saved = self.db.get(PlannerFlowBundleEvalSavedResult, saved_id)
        self.assertEqual(saved.payload_json, payload)
        self.assertEqual(int(saved.bundle_action_eval_id), slot_id)

    def test_repair_relinks_without_changing_result(self):
        slot_id, saved_id, payload = self._publish_and_save()
        self._delete_ibank_node(self.old_nid)
        new_nid = self._add_file_under_day("day-1", "إجراءات الاستطلاع.xlsx")
        self.db.flush()
        stats = repair_orphaned_action_eval_slots(self.db, exercise_id=1)
        self.db.flush()
        self.assertGreaterEqual(int(stats.get("remapped") or 0), 1)
        slot = self.db.get(ExercisePlannerFlowBundleActionEval, slot_id)
        saved = self.db.get(PlannerFlowBundleEvalSavedResult, saved_id)
        self.assertEqual(int(slot.id), slot_id)
        self.assertEqual(
            (slot.file_relpath or "").replace("\\", "/"),
            action_eval_storage_relpath(int(slot.bundle_id), new_nid),
        )
        self.assertEqual(int(saved.id), saved_id)
        self.assertEqual(saved.payload_json, payload)
        self.assertEqual(saved.total_pct, 88.0)
        self.assertTrue(saved.is_approved)
        dest = PLANNER_FLOW_BUNDLE_DIR / slot.file_relpath
        self.assertTrue(dest.is_file())

    def test_leftover_alias_day_root_not_purged(self):
        leftover_id = "day-1785903879298"
        leftover = InformationBankTreeNode(
            kind="action_eval",
            parent_id=None,
            name="اليوم/1",
            is_folder=True,
            catalog_phase_key=flow_day_catalog_key(leftover_id),
            sort_order=99,
            is_system=True,
        )
        self.db.add(leftover)
        self.db.commit()
        leftover_pk = int(leftover.id)
        invalidate_information_bank_kind_cache("action_eval")
        ensure_information_bank_kind(self.db, "action_eval")
        self.db.flush()
        still = self.db.get(InformationBankTreeNode, leftover_pk)
        self.assertIsNotNone(still)
        self.assertEqual(
            (still.catalog_phase_key or "").strip(),
            flow_day_catalog_key(leftover_id),
        )

    def test_empty_duplicate_hidden_result_kept(self):
        from app.action_eval_ibank_sync import dedupe_published_action_eval_slots
        from app.models import ExercisePlannerFlowBundle

        slot_id, saved_id, _payload = self._publish_and_save()
        bundle = (
            self.db.query(ExercisePlannerFlowBundle)
            .filter(ExercisePlannerFlowBundle.exercise_id == 1)
            .first()
        )
        dup = ExercisePlannerFlowBundleActionEval(
            bundle_id=int(bundle.id),
            slot_index=9,
            title="إجراءات الاستطلاع — معضلة 1: كمين على الاستطلاع",
            file_relpath=f"{int(bundle.id)}/ibn_999001.xlsx",
        )
        self.db.add(dup)
        self.db.flush()
        kept = dedupe_published_action_eval_slots(
            self.db,
            [
                self.db.get(ExercisePlannerFlowBundleActionEval, slot_id),
                dup,
            ],
        )
        self.assertEqual([int(s.id) for s in kept], [slot_id])
        self.assertIsNotNone(self.db.get(ExercisePlannerFlowBundleActionEval, int(dup.id)))
        self.assertIsNotNone(self.db.get(PlannerFlowBundleEvalSavedResult, saved_id))

    def test_two_saved_results_both_kept(self):
        from app.action_eval_ibank_sync import dedupe_published_action_eval_slots
        from app.models import ExercisePlannerFlowBundle

        slot_id, _saved_id, payload = self._publish_and_save()
        bundle = (
            self.db.query(ExercisePlannerFlowBundle)
            .filter(ExercisePlannerFlowBundle.exercise_id == 1)
            .first()
        )
        other = ExercisePlannerFlowBundleActionEval(
            bundle_id=int(bundle.id),
            slot_index=10,
            title="إجراءات الاستطلاع — معضلة 1: كمين على الاستطلاع",
            file_relpath=f"{int(bundle.id)}/ibn_999002.xlsx",
        )
        self.db.add(other)
        self.db.flush()
        self.db.add(
            PlannerFlowBundleEvalSavedResult(
                bundle_action_eval_id=int(other.id),
                exercise_id=1,
                exercise_phase="preparation",
                unit_level_key=self.unit_key,
                payload_json=payload,
                total_pct=70.0,
                grade_label="جيد",
                is_approved=False,
            )
        )
        self.db.flush()
        kept_ids = {
            int(s.id)
            for s in dedupe_published_action_eval_slots(
                self.db,
                [
                    self.db.get(ExercisePlannerFlowBundleActionEval, slot_id),
                    other,
                ],
            )
        }
        self.assertEqual(kept_ids, {slot_id, int(other.id)})


if __name__ == "__main__":
    unittest.main()
