"""ترحيل قوائم تقييم المعاضل عند تغيير مرحلة يوم المجرى، وإصلاح نشر حزمة فارغة."""
from __future__ import annotations

import json
import unittest
import zipfile
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.action_eval_ibank_sync import (
    build_judge_action_eval_display_groups,
    publish_action_eval_lists_from_ibank,
    publish_phase_action_eval_lists_from_ibank,
    published_action_eval_node_ids_for_bundle,
    remigrate_action_eval_slots_for_flow_day,
)
from app.analyst_dilemma_criteria import unit_keys_for_action_eval_flow_day
from app.analyst_flow_day_phase_link import set_ibank_flow_day_phase
from app.config import INFO_BANK_DIR
from app.database import Base
from app.info_bank_tree import (
    ensure_information_bank_kind,
    flow_day_catalog_key,
    invalidate_information_bank_kind_cache,
)
from app.models import (
    Exercise,
    ExercisePlannerFlowBundle,
    InformationBankEventFlowTable,
    InformationBankTreeNode,
    PlannerFlowBundleEvalSavedResult,
)


def _write_minimal_xlsx(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types></Types>')


class ActionEvalPhaseRemigrateTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
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
                                "note": "",
                                "phase_key": "battle_exposure",
                                "rows": [
                                    {
                                        "kind": "dilemma",
                                        "text": "المعضلة/1: تعرض سرية الاستطلاع لكمين",
                                    }
                                ],
                            },
                            {
                                "id": "day-2",
                                "label": "اليوم/2",
                                "note": "",
                                "phase_key": "battle_exposure",
                                "rows": [],
                            },
                        ],
                    },
                    ensure_ascii=False,
                )
            )
        )
        self.db.add(Exercise(id=1, code="T1", title="تمرين", owner_id=1))
        self.db.commit()
        invalidate_information_bank_kind_cache("action_eval")
        ensure_information_bank_kind(self.db, "action_eval")
        self.unit_key = "ul_brigade_grp_cmd"
        self.nid_day1 = self._add_file_under_day("day-1", "list-day1.xlsx")
        self.nid_day1b = self._add_file_under_day("day-1", "list-day1-b.xlsx")
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def _add_file_under_day(self, day_id: str, name: str) -> int:
        day_root = (
            self.db.query(InformationBankTreeNode)
            .filter(
                InformationBankTreeNode.kind == "action_eval",
                InformationBankTreeNode.catalog_phase_key == flow_day_catalog_key(day_id),
            )
            .first()
        )
        self.assertIsNotNone(day_root)
        folder = InformationBankTreeNode(
            kind="action_eval",
            parent_id=int(day_root.id),
            name="قيادة اللواء",
            is_folder=True,
            catalog_unit_key=self.unit_key,
            catalog_phase_key="",
            sort_order=0,
        )
        self.db.add(folder)
        self.db.flush()
        rel = f"action_eval/tree/test/{day_id}_{name}"
        dest = INFO_BANK_DIR / rel
        _write_minimal_xlsx(dest)
        file_node = InformationBankTreeNode(
            kind="action_eval",
            parent_id=int(folder.id),
            name=name,
            is_folder=False,
            catalog_unit_key=self.unit_key,
            catalog_phase_key=flow_day_catalog_key(day_id),
            file_relpath=rel.replace("\\", "/"),
            sort_order=0,
        )
        self.db.add(file_node)
        self.db.flush()
        return int(file_node.id)

    def _bundle(self, phase: str) -> ExercisePlannerFlowBundle | None:
        return (
            self.db.query(ExercisePlannerFlowBundle)
            .filter(
                ExercisePlannerFlowBundle.exercise_id == 1,
                ExercisePlannerFlowBundle.exercise_phase == phase,
                ExercisePlannerFlowBundle.unit_level_key == self.unit_key,
            )
            .first()
        )

    def test_publish_two_new_lists_to_empty_bundle_does_not_crash(self):
        stats = publish_phase_action_eval_lists_from_ibank(
            self.db,
            exercise_id=1,
            phase_key="preparation",
            selections_by_unit={self.unit_key: {self.nid_day1, self.nid_day1b}},
            flow_day_id="day-1",
        )
        self.db.commit()
        self.assertGreaterEqual(int(stats.get("added") or 0), 2)
        bundle = self._bundle("preparation")
        self.assertIsNotNone(bundle)
        published = published_action_eval_node_ids_for_bundle(self.db, bundle)
        self.assertIn(self.nid_day1, published)
        self.assertIn(self.nid_day1b, published)

    def test_remigrate_moves_day_one_lists_to_new_phase(self):
        publish_action_eval_lists_from_ibank(
            self.db,
            exercise_id=1,
            phase_key="battle_exposure",
            unit_key=self.unit_key,
            selected_node_ids={self.nid_day1},
            flow_day_id="day-1",
        )
        self.db.commit()
        old = self._bundle("battle_exposure")
        self.assertIsNotNone(old)
        self.assertIn(
            self.nid_day1, published_action_eval_node_ids_for_bundle(self.db, old)
        )

        stats = remigrate_action_eval_slots_for_flow_day(
            self.db,
            flow_day_id="day-1",
            new_phase_key="preparation",
            exercise_id=1,
        )
        self.db.commit()
        self.assertGreaterEqual(int(stats.get("moved") or 0), 1)
        new = self._bundle("preparation")
        self.assertIsNotNone(new)
        self.assertIn(
            self.nid_day1, published_action_eval_node_ids_for_bundle(self.db, new)
        )
        old = self._bundle("battle_exposure")
        if old is not None:
            self.assertNotIn(
                self.nid_day1, published_action_eval_node_ids_for_bundle(self.db, old)
            )

        day1_units = unit_keys_for_action_eval_flow_day(
            self.db, 1, phase_key="preparation", flow_day_id="day-1"
        )
        self.assertIn(self.unit_key, day1_units)
        day2_units = unit_keys_for_action_eval_flow_day(
            self.db, 1, phase_key="battle_exposure", flow_day_id="day-2"
        )
        self.assertNotIn(self.unit_key, day2_units)

    def test_ibank_phase_change_remigrates_and_keeps_saved_result(self):
        publish_action_eval_lists_from_ibank(
            self.db,
            exercise_id=1,
            phase_key="battle_exposure",
            unit_key=self.unit_key,
            selected_node_ids={self.nid_day1},
            flow_day_id="day-1",
        )
        self.db.commit()
        old = self._bundle("battle_exposure")
        slot_id = next(
            s.id
            for s in old.action_eval_slots
            if s.file_relpath and f"ibn_{self.nid_day1}." in (s.file_relpath or "")
        )
        self.db.add(
            PlannerFlowBundleEvalSavedResult(
                bundle_action_eval_id=int(slot_id),
                exercise_id=1,
                exercise_phase="battle_exposure",
                unit_level_key=self.unit_key,
                payload_json="{}",
            )
        )
        self.db.commit()

        changed = set_ibank_flow_day_phase(
            self.db, day_id="day-1", phase_key="preparation"
        )
        self.assertTrue(changed)
        self.db.commit()

        new = self._bundle("preparation")
        self.assertIsNotNone(new)
        self.assertIn(
            self.nid_day1, published_action_eval_node_ids_for_bundle(self.db, new)
        )
        saved = (
            self.db.query(PlannerFlowBundleEvalSavedResult)
            .filter(PlannerFlowBundleEvalSavedResult.bundle_action_eval_id == int(slot_id))
            .first()
        )
        self.assertIsNotNone(saved)
        self.assertEqual(saved.exercise_phase, "preparation")

        groups, _meta = build_judge_action_eval_display_groups(
            self.db, exercise_id=1, phase_key="preparation", flow_day_id="day-1"
        )
        self.assertTrue(any(g.get("unit_key") == self.unit_key for g in groups))


if __name__ == "__main__":
    unittest.main()
