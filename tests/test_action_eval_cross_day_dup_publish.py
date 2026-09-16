"""نشر قائمة في يوم لاحق لا يُمنع بنتيجة يوم سابق لنفس النص."""
from __future__ import annotations

import json
import unittest
import zipfile
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.action_eval_ibank_sync import (
    publish_action_eval_lists_from_ibank,
    published_action_eval_node_ids_for_bundle,
)
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

TEXT = "إنذار وهجوم صاروخي معادي على كتيبة المدفعية"
FLOW_JSON = {
    "version": 2,
    "active_day_id": "day-1",
    "days": [
        {
            "id": "day-1",
            "label": "اليوم/1",
            "note": "",
            "phase_key": "battle_exposure",
            "rows": [{"kind": "dilemma", "text": f"المعضلة/7: {TEXT}"}],
        },
        {
            "id": "day-2",
            "label": "اليوم/2",
            "note": "",
            "phase_key": "battle_exposure",
            "rows": [{"kind": "dilemma", "text": f"المعضلة/5: {TEXT}"}],
        },
    ],
}


def _write_minimal_xlsx(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types></Types>')


class CrossDaySavedDupPublishTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        self.db.add(InformationBankEventFlowTable(flow_table_json=json.dumps(FLOW_JSON, ensure_ascii=False)))
        self.db.add(Exercise(id=1, code="T1", title="تمرين", owner_id=1))
        self.db.commit()
        invalidate_information_bank_kind_cache("action_eval")
        ensure_information_bank_kind(self.db, "action_eval")
        self.unit_key = "ul_arty_bn_cmd"
        self.nid_d1 = self._add_file("day-1", "هجوم صاروخي على المدفعية.xlsx")
        self.nid_d2 = self._add_file("day-2", "هجوم صاروخي على المدفعية.xlsx")
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def _add_file(self, day_id: str, name: str) -> int:
        day_root = (
            self.db.query(InformationBankTreeNode)
            .filter(
                InformationBankTreeNode.kind == "action_eval",
                InformationBankTreeNode.catalog_phase_key == flow_day_catalog_key(day_id),
            )
            .first()
        )
        self.assertIsNotNone(day_root)
        rel = f"action_eval/tree/test/{day_id}_{name}"
        _write_minimal_xlsx(INFO_BANK_DIR / rel)
        node = InformationBankTreeNode(
            kind="action_eval",
            parent_id=int(day_root.id),
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

    def _bundle(self) -> ExercisePlannerFlowBundle:
        return (
            self.db.query(ExercisePlannerFlowBundle)
            .filter(
                ExercisePlannerFlowBundle.exercise_id == 1,
                ExercisePlannerFlowBundle.unit_level_key == self.unit_key,
            )
            .one()
        )

    def test_later_day_same_scenario_text_still_publishes(self):
        publish_action_eval_lists_from_ibank(
            self.db,
            exercise_id=1,
            phase_key="battle_exposure",
            unit_key=self.unit_key,
            selected_node_ids={self.nid_d1},
            dilemma_by_node={self.nid_d1: 1},
            flow_day_id="day-1",
        )
        self.db.flush()
        bundle = self._bundle()
        bundle.flow_table_json = json.dumps(FLOW_JSON, ensure_ascii=False)
        slot = next(
            s
            for s in bundle.action_eval_slots
            if (s.file_relpath or "").endswith(f"ibn_{self.nid_d1}.xlsx")
        )
        slot.title = f"هجوم صاروخي على المدفعية — معضلة 7: {TEXT}"
        self.db.add(
            PlannerFlowBundleEvalSavedResult(
                bundle_action_eval_id=int(slot.id),
                exercise_id=1,
                exercise_phase="battle_exposure",
                unit_level_key=self.unit_key,
                payload_json="{}",
            )
        )
        self.db.commit()

        stats = publish_action_eval_lists_from_ibank(
            self.db,
            exercise_id=1,
            phase_key="battle_exposure",
            unit_key=self.unit_key,
            selected_node_ids={self.nid_d2},
            dilemma_by_node={self.nid_d2: 2},
            flow_day_id="day-2",
        )
        self.db.commit()
        self.assertGreaterEqual(int(stats.get("added") or 0), 1, stats)
        self.assertEqual(int(stats.get("skipped") or 0), 0, stats)
        published = published_action_eval_node_ids_for_bundle(self.db, self._bundle())
        self.assertIn(self.nid_d1, published)
        self.assertIn(self.nid_d2, published)


if __name__ == "__main__":
    unittest.main()
