import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.info_bank_tree import (
    _apply_catalog_keys_from_parent,
    _backfill_unit_eval_folder_catalog,
    _unit_key_for_node,
    set_folder_unit_level,
)

from app.models import InformationBankTreeNode, InformationBankUnitLevel

KIND = "dilemma_eval"


class InfoBankTreeUnitLevelTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        self.phase = InformationBankTreeNode(
            kind=KIND,
            parent_id=None,
            name="الإعداد",
            is_folder=True,
            catalog_phase_key="preparation",
            is_system=True,
        )
        self.battalion = InformationBankTreeNode(
            kind=KIND,
            name="13. الكتيبة 12",
            is_folder=True,
            catalog_unit_key="ul_battalion_cmd",
        )
        self.company = InformationBankTreeNode(
            kind=KIND,
            name="السرية 3",
            is_folder=True,
            catalog_unit_key="ul_company_3",
        )
        self.db.add(self.phase)
        self.db.flush()
        self.battalion.parent_id = int(self.phase.id)
        self.db.add(self.battalion)
        self.db.flush()
        self.company.parent_id = int(self.battalion.id)
        self.db.add(self.company)
        self.db.commit()
        for key, label in (
            ("ul_battalion_cmd", "قيادة كتيبة"),
            ("ul_company_3", "السرية 3"),
        ):
            self.db.add(
                InformationBankUnitLevel(
                    key=key,
                    label=label,
                    included_in_exercise=True,
                )
            )
        self.db.commit()

    def test_backfill_does_not_overwrite_child_unit_level(self):
        changed = _backfill_unit_eval_folder_catalog(self.db, KIND)
        self.db.commit()
        company = self.db.get(InformationBankTreeNode, int(self.company.id))
        self.assertEqual((company.catalog_unit_key or "").strip(), "ul_company_3")
        self.assertFalse(changed)

    def test_apply_catalog_from_parent_only_fills_missing(self):
        child = self.db.get(InformationBankTreeNode, int(self.company.id))
        _apply_catalog_keys_from_parent(self.db, child, self.battalion)
        self.assertEqual((child.catalog_unit_key or "").strip(), "ul_company_3")

    def test_set_parent_does_not_reset_child_folder_unit_level(self):
        set_folder_unit_level(
            self.db,
            kind=KIND,
            node_id=int(self.battalion.id),
            unit_key="ul_battalion_cmd",
        )
        self.db.commit()
        company = self.db.get(InformationBankTreeNode, int(self.company.id))
        self.assertEqual((company.catalog_unit_key or "").strip(), "ul_company_3")

    def test_set_parent_leaves_empty_subfolder_without_unit_key(self):
        empty_co = InformationBankTreeNode(
            kind=KIND,
            name="السرية/1",
            is_folder=True,
            parent_id=int(self.battalion.id),
        )
        self.db.add(empty_co)
        self.db.commit()
        set_folder_unit_level(
            self.db,
            kind=KIND,
            node_id=int(self.battalion.id),
            unit_key="ul_battalion_cmd",
        )
        self.db.commit()
        sub = self.db.get(InformationBankTreeNode, int(empty_co.id))
        self.assertEqual((sub.catalog_unit_key or "").strip(), "")

    def test_file_under_empty_subfolder_does_not_inherit_battalion_key(self):
        empty_co = InformationBankTreeNode(
            kind=KIND,
            name="السرية/2",
            is_folder=True,
            parent_id=int(self.battalion.id),
        )
        self.db.add(empty_co)
        self.db.flush()
        xlsx = InformationBankTreeNode(
            kind=KIND,
            name="قائمة.xlsx",
            is_folder=False,
            parent_id=int(empty_co.id),
        )
        self.db.add(xlsx)
        self.db.commit()
        set_folder_unit_level(
            self.db,
            kind=KIND,
            node_id=int(self.battalion.id),
            unit_key="ul_battalion_cmd",
        )
        self.db.commit()
        leaf = self.db.get(InformationBankTreeNode, int(xlsx.id))
        self.assertEqual(_unit_key_for_node(self.db, leaf), "")


if __name__ == "__main__":
    unittest.main()
