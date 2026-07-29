"""اختبارات إصلاح نشر قوائم تقييم الإجراءات (تخطي صامت / unit_key فارغ)."""

from __future__ import annotations

import json
import unittest
import zipfile
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.action_eval_ibank_sync import (
    publish_action_eval_lists_from_ibank,
    publish_phase_action_eval_lists_from_ibank,
    published_action_eval_node_ids_for_bundle,
)
from app.config import INFO_BANK_DIR
from app.database import Base
from app.ibank_dilemma_lists import (
    DILEMMA_LISTS_KIND,
    ensure_dilemma_lists_root,
    set_list_unit_assignments,
)
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
    InformationBankUnitLevel,
)


def _write_minimal_xlsx(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types></Types>')


class ActionEvalPublishFixTests(unittest.TestCase):
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
        self.db.add(
            InformationBankUnitLevel(
                key="ul_test_med",
                label="السرية الطبية",
                brigade_group="1",
                included_in_exercise=True,
            )
        )
        self.db.commit()
        invalidate_information_bank_kind_cache("action_eval")
        ensure_information_bank_kind(self.db, "action_eval")
        self.unit_key = "ul_brigade_grp_cmd"

    def tearDown(self):
        self.db.close()

    def _add_orphan_file(self, name: str) -> int:
        """ملف تحت يوم المجرى بدون مجلد وحدة — يظهر في الواجهة لكن لا يُفهرس تحت الوحدة."""
        day_root = (
            self.db.query(InformationBankTreeNode)
            .filter(
                InformationBankTreeNode.kind == "action_eval",
                InformationBankTreeNode.catalog_phase_key == flow_day_catalog_key("day-1"),
            )
            .first()
        )
        self.assertIsNotNone(day_root)
        rel = f"action_eval/tree/orphan/{name}"
        dest = INFO_BANK_DIR / rel
        _write_minimal_xlsx(dest)
        node = InformationBankTreeNode(
            kind="action_eval",
            parent_id=int(day_root.id),
            name=name,
            is_folder=False,
            catalog_unit_key=self.unit_key,
            catalog_phase_key=flow_day_catalog_key("day-1"),
            file_relpath=rel.replace("\\", "/"),
            sort_order=0,
        )
        self.db.add(node)
        self.db.flush()
        return int(node.id)

    def test_publish_direct_node_when_not_in_unit_folder_index(self):
        nid = self._add_orphan_file("orphan-list.xlsx")
        self.db.commit()
        stats = publish_action_eval_lists_from_ibank(
            self.db,
            exercise_id=1,
            phase_key="battle_exposure",
            unit_key=self.unit_key,
            selected_node_ids={nid},
            flow_day_id="day-1",
        )
        self.db.commit()
        self.assertGreaterEqual(int(stats.get("added", 0)), 1)
        self.assertEqual(int(stats.get("skipped", 0)), 0)
        bundle = (
            self.db.query(ExercisePlannerFlowBundle)
            .filter(ExercisePlannerFlowBundle.unit_level_key == self.unit_key)
            .first()
        )
        self.assertIsNotNone(bundle)
        self.assertIn(nid, published_action_eval_node_ids_for_bundle(self.db, bundle))

    def test_phase_publish_resolves_empty_unit_key_selection(self):
        nid = self._add_orphan_file("orphan-empty-uk.xlsx")
        self.db.commit()
        stats = publish_phase_action_eval_lists_from_ibank(
            self.db,
            exercise_id=1,
            phase_key="battle_exposure",
            selections_by_unit={"": {nid}},
            flow_day_id="day-1",
        )
        self.db.commit()
        self.assertGreaterEqual(
            int(stats.get("added", 0)) + int(stats.get("updated", 0)), 1
        )

    def test_phase_publish_keeps_same_node_for_multiple_assigned_units(self):
        nid = self._add_orphan_file("shared-threat.xlsx")
        root = ensure_dilemma_lists_root(self.db)
        list_node = InformationBankTreeNode(
            kind=DILEMMA_LISTS_KIND,
            parent_id=int(root.id),
            name="shared-threat.xlsx",
            is_folder=False,
            file_relpath="dilemma_lists/tree/n1/shared-threat.xlsx",
            sort_order=0,
            is_system=False,
        )
        self.db.add(list_node)
        self.db.flush()
        set_list_unit_assignments(
            self.db,
            list_node_id=int(list_node.id),
            unit_keys={self.unit_key, "ul_test_med"},
        )
        self.db.commit()

        stats = publish_phase_action_eval_lists_from_ibank(
            self.db,
            exercise_id=1,
            phase_key="battle_exposure",
            selections_by_unit={
                self.unit_key: {nid},
                "ul_test_med": {nid},
            },
            flow_day_id="day-1",
        )
        self.db.commit()

        self.assertEqual(int(stats.get("units", 0)), 2)
        bundles = (
            self.db.query(ExercisePlannerFlowBundle)
            .filter(ExercisePlannerFlowBundle.unit_level_key.in_([self.unit_key, "ul_test_med"]))
            .all()
        )
        published_by_unit = {
            (b.unit_level_key or "").strip(): published_action_eval_node_ids_for_bundle(
                self.db, b
            )
            for b in bundles
        }
        self.assertIn(nid, published_by_unit.get(self.unit_key, set()))
        self.assertIn(nid, published_by_unit.get("ul_test_med", set()))


if __name__ == "__main__":
    unittest.main()
