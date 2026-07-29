"""اختبارات تبويب قوائم تقييم المعاضل وفرض الوحدات على قوائم الإجراءات."""

from __future__ import annotations

import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.ibank_dilemma_lists import (
    DILEMMA_LISTS_KIND,
    assigned_units_for_action_eval_name,
    apply_dilemma_list_units_to_action_eval,
    build_dilemma_lists_page_payload,
    ensure_dilemma_lists_root,
    normalize_list_basename,
    set_list_unit_assignments,
)
from app.info_bank_tree import kind_tab
from app.models import InformationBankTreeNode, InformationBankUnitLevel


class DilemmaListsTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()

    def tearDown(self):
        self.db.close()

    def test_normalize_list_basename_strips_ext_and_hamza(self):
        self.assertEqual(
            normalize_list_basename("قائمة تقييم.xlsx"),
            normalize_list_basename("قائمه تقييم.XLSX"),
        )

    def test_kind_tab_dilemma_lists(self):
        self.assertEqual(kind_tab("dilemma_lists"), "dilemma-lists")

    def test_assign_applies_single_unit_to_action_eval(self):
        root = ensure_dilemma_lists_root(self.db)
        self.db.add(
            InformationBankUnitLevel(
                key="ul_test_cmd",
                label="قيادة اختبار",
                brigade_group="1",
                sort_order=1,
                included_in_exercise=True,
                is_system=False,
            )
        )
        list_node = InformationBankTreeNode(
            kind=DILEMMA_LISTS_KIND,
            parent_id=int(root.id),
            name="قائمة معضلة اختبار.xlsx",
            is_folder=False,
            file_relpath="dilemma_lists/tree/n1/q.xlsx",
            sort_order=0,
            is_system=False,
        )
        ae_node = InformationBankTreeNode(
            kind="action_eval",
            parent_id=None,
            name="قائمة معضلة اختبار.xlsx",
            is_folder=False,
            file_relpath="action_eval/tree/n2/q.xlsx",
            catalog_unit_key="",
            sort_order=0,
            is_system=False,
        )
        self.db.add_all([list_node, ae_node])
        self.db.flush()

        set_list_unit_assignments(
            self.db, list_node_id=int(list_node.id), unit_keys={"ul_test_cmd"}
        )
        updated = apply_dilemma_list_units_to_action_eval(self.db)
        self.db.commit()

        self.assertGreaterEqual(updated, 1)
        self.db.refresh(ae_node)
        self.assertEqual((ae_node.catalog_unit_key or "").strip(), "ul_test_cmd")

        payload = build_dilemma_lists_page_payload(self.db)
        self.assertEqual(payload["root_id"], int(root.id))
        match = next(x for x in payload["lists"] if x["id"] == int(list_node.id))
        self.assertIn("ul_test_cmd", match["selected_unit_keys"])

    def test_assigned_units_for_action_eval_name_returns_all_units(self):
        root = ensure_dilemma_lists_root(self.db)
        self.db.add_all(
            [
                InformationBankUnitLevel(
                    key="ul_test_cmd",
                    label="قيادة اختبار",
                    brigade_group="1",
                    sort_order=1,
                    included_in_exercise=True,
                    is_system=False,
                ),
                InformationBankUnitLevel(
                    key="ul_test_med",
                    label="السرية الطبية",
                    brigade_group="1",
                    sort_order=2,
                    included_in_exercise=True,
                    is_system=False,
                ),
            ]
        )
        list_node = InformationBankTreeNode(
            kind=DILEMMA_LISTS_KIND,
            parent_id=int(root.id),
            name="تهديد جوي.xlsx",
            is_folder=False,
            file_relpath="dilemma_lists/tree/n1/threat.xlsx",
            sort_order=0,
            is_system=False,
        )
        self.db.add(list_node)
        self.db.flush()
        set_list_unit_assignments(
            self.db,
            list_node_id=int(list_node.id),
            unit_keys={"ul_test_cmd", "ul_test_med"},
        )

        assigned = assigned_units_for_action_eval_name(self.db, "تهديد جوي.xlsx")
        self.assertEqual(assigned, {"ul_test_cmd", "ul_test_med"})


if __name__ == "__main__":
    unittest.main()
