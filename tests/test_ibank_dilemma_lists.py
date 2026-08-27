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
    def test_unmatched_action_eval_clears_guessed_unit(self):
        ae_node = InformationBankTreeNode(
            kind="action_eval",
            parent_id=None,
            name="قائمة بلا مطابقة.xlsx",
            is_folder=False,
            file_relpath="action_eval/tree/n9/x.xlsx",
            catalog_unit_key="ul_test_cmd",
            sort_order=0,
            is_system=False,
        )
        self.db.add(ae_node)
        self.db.flush()
        apply_dilemma_list_units_to_action_eval(self.db)
        self.db.commit()
        self.db.refresh(ae_node)
        self.assertEqual((ae_node.catalog_unit_key or "").strip(), "")

    def test_folder_unit_stays_empty_excel_file_gets_unit(self):
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
            name="إخلاء آلية.xlsx",
            is_folder=False,
            file_relpath="dilemma_lists/tree/n1/evac.xlsx",
            sort_order=0,
            is_system=False,
        )
        day = InformationBankTreeNode(
            kind="action_eval",
            parent_id=None,
            name="اليوم/1",
            is_folder=True,
            catalog_phase_key="flow_day:day-1",
            catalog_unit_key="",
            sort_order=0,
            is_system=True,
        )
        self.db.add_all([list_node, day])
        self.db.flush()
        folder = InformationBankTreeNode(
            kind="action_eval",
            parent_id=int(day.id),
            name="المعضلة/1 فرض الصمت",
            is_folder=True,
            catalog_unit_key="ul_wrong",
            sort_order=0,
            is_system=False,
        )
        self.db.add(folder)
        self.db.flush()
        ae_file = InformationBankTreeNode(
            kind="action_eval",
            parent_id=int(folder.id),
            name="إخلاء آلية.xlsx",
            is_folder=False,
            file_relpath="action_eval/tree/n3/evac.xlsx",
            catalog_unit_key="",
            sort_order=0,
            is_system=False,
        )
        self.db.add(ae_file)
        self.db.flush()
        set_list_unit_assignments(
            self.db, list_node_id=int(list_node.id), unit_keys={"ul_test_cmd"}
        )
        apply_dilemma_list_units_to_action_eval(self.db)
        self.db.commit()
        self.db.refresh(folder)
        self.db.refresh(ae_file)
        self.assertEqual((ae_file.catalog_unit_key or "").strip(), "ul_test_cmd")
        self.assertEqual((folder.catalog_unit_key or "").strip(), "")

    def test_multiple_units_preserve_valid_choice(self):
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
        ae_node = InformationBankTreeNode(
            kind="action_eval",
            parent_id=None,
            name="تهديد جوي.xlsx",
            is_folder=False,
            file_relpath="action_eval/tree/n2/threat.xlsx",
            catalog_unit_key="ul_test_cmd",
            sort_order=0,
            is_system=False,
        )
        self.db.add_all([list_node, ae_node])
        self.db.flush()
        set_list_unit_assignments(
            self.db,
            list_node_id=int(list_node.id),
            unit_keys={"ul_test_cmd", "ul_test_med"},
        )
        apply_dilemma_list_units_to_action_eval(self.db)
        self.db.commit()
        self.db.refresh(ae_node)
        self.assertEqual((ae_node.catalog_unit_key or "").strip(), "ul_test_cmd")

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
        self.assertEqual(
            assigned_units_for_action_eval_name(self.db, "وصف المعضلة.docx"),
            set(),
        )

    def test_docx_file_does_not_get_unit(self):
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
            name="وصف المعضلة.xlsx",
            is_folder=False,
            file_relpath="dilemma_lists/tree/n1/desc.xlsx",
            sort_order=0,
            is_system=False,
        )
        ae_docx = InformationBankTreeNode(
            kind="action_eval",
            parent_id=None,
            name="وصف المعضلة.docx",
            is_folder=False,
            file_relpath="action_eval/tree/n2/desc.docx",
            catalog_unit_key="ul_test_cmd",
            sort_order=0,
            is_system=False,
        )
        self.db.add_all([list_node, ae_docx])
        self.db.flush()
        set_list_unit_assignments(
            self.db, list_node_id=int(list_node.id), unit_keys={"ul_test_cmd"}
        )
        apply_dilemma_list_units_to_action_eval(self.db)
        self.db.commit()
        self.db.refresh(ae_docx)
        self.assertEqual((ae_docx.catalog_unit_key or "").strip(), "")

    def test_multiple_units_leave_empty_when_none_chosen(self):
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
        ae_node = InformationBankTreeNode(
            kind="action_eval",
            parent_id=None,
            name="تهديد جوي.xlsx",
            is_folder=False,
            file_relpath="action_eval/tree/n2/threat.xlsx",
            catalog_unit_key="",
            sort_order=0,
            is_system=False,
        )
        self.db.add_all([list_node, ae_node])
        self.db.flush()
        set_list_unit_assignments(
            self.db,
            list_node_id=int(list_node.id),
            unit_keys={"ul_test_cmd", "ul_test_med"},
        )
        apply_dilemma_list_units_to_action_eval(self.db)
        self.db.commit()
        self.db.refresh(ae_node)
        self.assertEqual((ae_node.catalog_unit_key or "").strip(), "")

    def test_manual_choice_saved_for_multi_unit_list(self):
        from app.ibank_dilemma_lists import set_action_eval_file_unit_choice

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
        ae_node = InformationBankTreeNode(
            kind="action_eval",
            parent_id=None,
            name="تهديد جوي.xlsx",
            is_folder=False,
            file_relpath="action_eval/tree/n2/threat.xlsx",
            catalog_unit_key="",
            sort_order=0,
            is_system=False,
        )
        self.db.add_all([list_node, ae_node])
        self.db.flush()
        set_list_unit_assignments(
            self.db,
            list_node_id=int(list_node.id),
            unit_keys={"ul_test_cmd", "ul_test_med"},
        )
        set_action_eval_file_unit_choice(
            self.db, node_id=int(ae_node.id), unit_key="ul_test_med"
        )
        self.db.commit()
        self.db.refresh(ae_node)
        self.assertEqual((ae_node.catalog_unit_key or "").strip(), "ul_test_med")
        apply_dilemma_list_units_to_action_eval(self.db)
        self.db.commit()
        self.db.refresh(ae_node)
        self.assertEqual((ae_node.catalog_unit_key or "").strip(), "ul_test_med")

    def test_match_files_uses_chosen_unit_only(self):
        from app.ibank_action_eval_dilemma_tree import _match_files_to_assignees

        meta = {
            "name": "تهديد جوي.xlsx",
            "procedure_title": "تهديد جوي",
            "unit_key": "ul_test_med",
            "assigned_unit_keys": ["ul_test_cmd", "ul_test_med"],
        }
        matched = _match_files_to_assignees(
            ["محكم القيادة", "محكم الطبية"],
            [meta],
            assignee_unit_keys={
                "محكم القيادة": "ul_test_cmd",
                "محكم الطبية": "ul_test_med",
            },
        )
        self.assertEqual(len(matched["محكم الطبية"]), 1)
        self.assertEqual(len(matched["محكم القيادة"]), 0)

    def test_match_files_holds_multi_unit_until_chosen(self):
        from app.ibank_action_eval_dilemma_tree import _match_files_to_assignees

        meta = {
            "name": "تهديد جوي.xlsx",
            "procedure_title": "تهديد جوي",
            "unit_key": "",
            "assigned_unit_keys": ["ul_test_cmd", "ul_test_med"],
        }
        matched = _match_files_to_assignees(
            ["محكم القيادة", "محكم الطبية"],
            [meta],
            assignee_unit_keys={
                "محكم القيادة": "ul_test_cmd",
                "محكم الطبية": "ul_test_med",
            },
        )
        self.assertEqual(len(matched["محكم الطبية"]), 0)
        self.assertEqual(len(matched["محكم القيادة"]), 0)
        self.assertEqual(len(matched.get("__unassigned__") or []), 1)


if __name__ == "__main__":
    unittest.main()
