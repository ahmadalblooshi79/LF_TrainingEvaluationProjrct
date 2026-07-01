"""اختبار: السماح برفع الملفات تحت مجلد محدّد."""
from __future__ import annotations

import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.info_bank_tree import (
    _unit_key_for_node,
    _unit_key_for_upload_target,
)
from app.models import InformationBankTreeNode

KIND = "dilemma_eval"


class InfoBankUploadTargetTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        self.phase = InformationBankTreeNode(
            kind=KIND,
            parent_id=None,
            name="مرحلة الانفتاح",
            is_folder=True,
            catalog_phase_key="opening",
            sort_order=0,
        )
        self.db.add(self.phase)
        self.db.flush()
        self.battalion = InformationBankTreeNode(
            kind=KIND,
            parent_id=int(self.phase.id),
            name="قيادة كتيبة 12",
            is_folder=True,
            catalog_unit_key="ul_mech2_bn_cmd",
            sort_order=0,
        )
        self.db.add(self.battalion)
        self.db.flush()
        self.company = InformationBankTreeNode(
            kind=KIND,
            parent_id=int(self.battalion.id),
            name="السرية 1",
            is_folder=True,
            sort_order=0,
        )
        self.db.add(self.company)
        self.db.commit()

    def test_nested_folder_inherits_parent_unit_for_upload(self):
        self.assertEqual(_unit_key_for_node(self.db, self.company), "")
        self.assertEqual(
            _unit_key_for_upload_target(self.db, self.company),
            "ul_mech2_bn_cmd",
        )

    def test_battalion_with_explicit_key_allows_upload(self):
        self.assertEqual(
            _unit_key_for_upload_target(self.db, self.battalion),
            "ul_mech2_bn_cmd",
        )


if __name__ == "__main__":
    unittest.main()
