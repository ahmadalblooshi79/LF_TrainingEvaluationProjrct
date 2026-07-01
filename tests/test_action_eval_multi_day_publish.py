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
)
from app.models import (
    Exercise,
    ExercisePlannerFlowBundleActionEval,
    InformationBankEventFlowTable,
    InformationBankTreeNode,
)


def _write_minimal_xlsx(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types></Types>')


class ActionEvalMultiDayPublishTests(unittest.TestCase):
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
                            {"id": "day-1", "label": "اليوم/1", "note": "", "rows": []},
                            {"id": "day-2", "label": "اليوم/2", "note": "", "rows": []},
                        ],
                    },
                    ensure_ascii=False,
                )
            )
        )
        self.db.add(
            Exercise(id=1, code="T1", title="تمرين", owner_id=1)
        )
        self.db.commit()
        ensure_information_bank_kind(self.db, "action_eval")
        self.unit_key = "ul_brigade_grp_cmd"
        self.nid_day1, self.nid_day2 = self._seed_ibank_files()
        self.db.commit()

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
        rel = f"action_eval/tree/test/{day_id}_{name}.xlsx"
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

    def _seed_ibank_files(self) -> tuple[int, int]:
        return (
            self._add_file_under_day("day-1", "list-day1.xlsx"),
            self._add_file_under_day("day-2", "list-day2.xlsx"),
        )

    def _bundle_after_publish(self):
        from app.models import ExercisePlannerFlowBundle

        return (
            self.db.query(ExercisePlannerFlowBundle)
            .filter(
                ExercisePlannerFlowBundle.exercise_id == 1,
                ExercisePlannerFlowBundle.unit_level_key == self.unit_key,
            )
            .first()
        )

    def test_publish_day_two_preserves_day_one(self):
        publish_action_eval_lists_from_ibank(
            self.db,
            exercise_id=1,
            phase_key="preparation",
            unit_key=self.unit_key,
            selected_node_ids={self.nid_day1},
            flow_day_id="day-1",
        )
        self.db.flush()
        bundle = self._bundle_after_publish()
        self.assertIsNotNone(bundle)
        self.assertEqual(
            published_action_eval_node_ids_for_bundle(self.db, bundle),
            {self.nid_day1},
        )

        publish_action_eval_lists_from_ibank(
            self.db,
            exercise_id=1,
            phase_key="preparation",
            unit_key=self.unit_key,
            selected_node_ids={self.nid_day2},
            flow_day_id="day-2",
        )
        self.db.flush()
        published = published_action_eval_node_ids_for_bundle(self.db, bundle)
        self.assertIn(self.nid_day1, published)
        self.assertIn(self.nid_day2, published)

    def test_publish_day_two_can_unpublish_only_that_day(self):
        publish_action_eval_lists_from_ibank(
            self.db,
            exercise_id=1,
            phase_key="preparation",
            unit_key=self.unit_key,
            selected_node_ids={self.nid_day1, self.nid_day2},
            flow_day_id="day-1",
        )
        publish_action_eval_lists_from_ibank(
            self.db,
            exercise_id=1,
            phase_key="preparation",
            unit_key=self.unit_key,
            selected_node_ids={self.nid_day2},
            flow_day_id="day-2",
        )
        self.db.flush()
        bundle = self._bundle_after_publish()
        published = published_action_eval_node_ids_for_bundle(self.db, bundle)
        self.assertIn(self.nid_day1, published)
        self.assertIn(self.nid_day2, published)

        publish_action_eval_lists_from_ibank(
            self.db,
            exercise_id=1,
            phase_key="preparation",
            unit_key=self.unit_key,
            selected_node_ids=set(),
            flow_day_id="day-2",
        )
        self.db.flush()
        published = published_action_eval_node_ids_for_bundle(self.db, bundle)
        self.assertIn(self.nid_day1, published)
        self.assertNotIn(self.nid_day2, published)

    def test_publish_day_two_sixth_list_avoids_slot_six_collision(self):
        """يوم1 بخمس قوائم ثم يوم2 بست — السادسة لا تُعاد استخدام 6 المحجوز مؤقتاً."""
        day1_ids = [
            self._add_file_under_day("day-1", f"list-day1-{i}.xlsx") for i in range(5)
        ]
        day2_ids = [
            self._add_file_under_day("day-2", f"list-day2-{i}.xlsx") for i in range(6)
        ]
        self.db.commit()

        publish_action_eval_lists_from_ibank(
            self.db,
            exercise_id=1,
            phase_key="preparation",
            unit_key=self.unit_key,
            selected_node_ids=set(day1_ids),
            flow_day_id="day-1",
        )
        publish_action_eval_lists_from_ibank(
            self.db,
            exercise_id=1,
            phase_key="preparation",
            unit_key=self.unit_key,
            selected_node_ids=set(day2_ids),
            flow_day_id="day-2",
        )
        self.db.commit()
        bundle = self._bundle_after_publish()
        slots = (
            self.db.query(ExercisePlannerFlowBundleActionEval)
            .filter(ExercisePlannerFlowBundleActionEval.bundle_id == int(bundle.id))
            .all()
        )
        indexes = [int(s.slot_index) for s in slots]
        self.assertEqual(len(indexes), 11)
        self.assertEqual(len(indexes), len(set(indexes)))


if __name__ == "__main__":
    unittest.main()
