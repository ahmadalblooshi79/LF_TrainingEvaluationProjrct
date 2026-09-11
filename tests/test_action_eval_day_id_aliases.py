# -*- coding: utf-8 -*-
"""مطابقة أيام المجرى عند اختلاف معرّف اليوم بين التخطيط وبنك المعلومات."""

from __future__ import annotations

import json
import unittest
import zipfile
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.action_eval_ibank_sync import (
    _flow_day_id_for_node,
    _flow_day_root_nodes_for_id,
    build_action_eval_dilemma_publish_groups,
    collect_flow_assignee_units_for_phase,
    collect_flow_day_tabs_for_exercise,
)
from app.config import INFO_BANK_DIR
from app.database import Base
from app.flow_day_ids import (
    canonical_flow_day_id,
    flow_day_ordinal,
    flow_days_equivalent,
)
from app.ibank_action_eval_dilemma_tree import invalidate_action_eval_dilemma_tree_cache
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

IBANK_DAY2 = "day-1788070146115"
PLANNER_DAY2 = "day-1788936502475"
LEFTOVER_DAY2 = "day-1785903879298"
IBANK_DAY3 = "day-1788070499786"


def _write_minimal_xlsx(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types></Types>')


def _flow_rows(*assignee: str) -> list[dict]:
    return [
        {"kind": "dilemma", "text": "المعضلة/1: كمين على الاستطلاع", "assignee": ""},
        {
            "kind": "row",
            "text": "إجراء",
            "assignee": "\n".join(assignee),
        },
    ]


class FlowDayOrdinalTests(unittest.TestCase):
    def test_short_id_and_label(self):
        self.assertEqual(flow_day_ordinal("day-1", ""), 1)
        self.assertEqual(flow_day_ordinal("day-2", "اليوم/2"), 2)
        self.assertEqual(flow_day_ordinal("day-1788070146115", "اليوم/2"), 2)
        self.assertIsNone(flow_day_ordinal("day-1788070146115", ""))
        self.assertEqual(flow_day_ordinal("", "اليوم 3"), 3)


class ActionEvalMismatchedDayIdTests(unittest.TestCase):
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
                                "rows": _flow_rows("محكم قيادة مجموعة اللواء"),
                            },
                            {
                                "id": IBANK_DAY2,
                                "label": "اليوم/2",
                                "phase_key": "battle_exposure",
                                "rows": _flow_rows("محكم قيادة مجموعة اللواء"),
                            },
                            {
                                "id": IBANK_DAY3,
                                "label": "اليوم/3",
                                "phase_key": "battle_exposure",
                                "rows": _flow_rows("محكم الطبية"),
                            },
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
        self.db.add(
            ExercisePlannerFlowBundle(
                exercise_id=1,
                exercise_phase="preparation",
                unit_level_key="ul_brigade_grp_cmd",
                unit_level_label="قيادة مجموعة اللواء",
                flow_table_json=json.dumps(
                    {
                        "version": 2,
                        "active_day_id": "day-1",
                        "days": [
                            {
                                "id": "day-1",
                                "label": "اليوم/1",
                                "phase_key": "battle_exposure",
                                "rows": _flow_rows("محكم قيادة مجموعة اللواء"),
                            },
                            {
                                "id": PLANNER_DAY2,
                                "label": "اليوم/2",
                                "phase_key": "battle_exposure",
                                "rows": _flow_rows("محكم قيادة مجموعة اللواء"),
                            },
                        ],
                    },
                    ensure_ascii=False,
                ),
            )
        )
        self.db.commit()
        invalidate_information_bank_kind_cache("action_eval")
        invalidate_action_eval_dilemma_tree_cache()
        ensure_information_bank_kind(self.db, "action_eval")
        self.nid_day2 = self._add_file_under_day(IBANK_DAY2, "list-day2.xlsx")
        leftover = InformationBankTreeNode(
            kind="action_eval",
            parent_id=None,
            name="اليوم/2",
            is_folder=True,
            catalog_phase_key=flow_day_catalog_key(LEFTOVER_DAY2),
            sort_order=99,
        )
        self.db.add(leftover)
        self.db.flush()
        self.nid_leftover = self._add_file_under_parent(
            int(leftover.id), LEFTOVER_DAY2, "list-leftover.xlsx"
        )
        self.db.commit()
        invalidate_action_eval_dilemma_tree_cache()

    def tearDown(self):
        self.db.close()

    def _add_file_under_parent(self, parent_id: int, day_id: str, name: str) -> int:
        folder = InformationBankTreeNode(
            kind="action_eval",
            parent_id=int(parent_id),
            name="معضلة 1",
            is_folder=True,
            catalog_unit_key=self.unit_key,
            catalog_phase_key="",
            sort_order=0,
        )
        self.db.add(folder)
        self.db.flush()
        rel = f"action_eval/tree/alias/{day_id}_{name}"
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

    def _add_file_under_day(self, day_id: str, name: str) -> int:
        day_root = (
            self.db.query(InformationBankTreeNode)
            .filter(
                InformationBankTreeNode.kind == "action_eval",
                InformationBankTreeNode.catalog_phase_key == flow_day_catalog_key(day_id),
                InformationBankTreeNode.parent_id.is_(None),
            )
            .first()
        )
        self.assertIsNotNone(day_root)
        return self._add_file_under_parent(int(day_root.id), day_id, name)

    def test_aliases_treat_planner_and_ibank_day2_as_same_day(self):
        self.assertTrue(flow_days_equivalent(self.db, PLANNER_DAY2, IBANK_DAY2))
        self.assertEqual(canonical_flow_day_id(self.db, PLANNER_DAY2), IBANK_DAY2)

    def test_tabs_include_ibank_only_days_and_canonical_day2(self):
        tabs = collect_flow_day_tabs_for_exercise(
            self.db, exercise_id=1, phase_key="preparation"
        )
        ids = [t["id"] for t in tabs]
        labels = [t["label"] for t in tabs]
        self.assertIn("اليوم/1", labels)
        self.assertIn("اليوم/2", labels)
        self.assertIn("اليوم/3", labels)
        self.assertIn(IBANK_DAY2, ids)
        self.assertNotIn(PLANNER_DAY2, ids)
        self.assertIn(IBANK_DAY3, ids)

    def test_publish_groups_resolve_planner_day_id(self):
        groups, meta = build_action_eval_dilemma_publish_groups(
            self.db,
            exercise_id=1,
            phase_key="preparation",
            flow_day_id=PLANNER_DAY2,
        )
        self.assertGreaterEqual(int(meta.get("dilemmas") or 0), 1)
        self.assertTrue(groups)
        node_ids = {
            int(row["node_id"])
            for g in groups
            for j in g.get("judges") or []
            for row in j.get("rows") or []
            if row.get("node_id")
        }
        self.assertIn(self.nid_day2, node_ids)
        self.assertIn(self.nid_leftover, node_ids)

    def test_pull_assignees_match_planner_or_ibank_day(self):
        from_planner = collect_flow_assignee_units_for_phase(
            self.db,
            exercise_id=1,
            phase_key="preparation",
            flow_day_id=PLANNER_DAY2,
        )
        self.assertIn(self.unit_key, from_planner)
        from_day3 = collect_flow_assignee_units_for_phase(
            self.db,
            exercise_id=1,
            phase_key="preparation",
            flow_day_id=IBANK_DAY3,
        )
        self.assertTrue(from_day3)

    def test_file_nodes_under_ibank_folder_match_planner_day(self):
        roots = _flow_day_root_nodes_for_id(self.db, PLANNER_DAY2)
        catalog_keys = {n.catalog_phase_key for n in roots}
        self.assertIn(flow_day_catalog_key(IBANK_DAY2), catalog_keys)
        self.assertIn(flow_day_catalog_key(LEFTOVER_DAY2), catalog_keys)
        node = self.db.get(InformationBankTreeNode, self.nid_day2)
        self.assertTrue(
            flow_days_equivalent(
                self.db, _flow_day_id_for_node(self.db, node), PLANNER_DAY2
            )
        )
