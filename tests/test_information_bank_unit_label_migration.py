"""اختبار ترحيل تسمية قيادة كتيبة المشاة الآلية/12 في بنك المعلومات."""
from __future__ import annotations

import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.information_bank_catalog import apply_information_bank_unit_label_migrations
from app.models import InformationBankUnitLevel
from app.models.domain import Base


class TestInformationBankUnitLabelMigration(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()
        self.db.add(
            InformationBankUnitLevel(
                key="ul_mech2_bn_cmd",
                label="قيادة كتيبة المشاة الآلية/2",
                brigade_group="1",
                sort_order=2,
                is_system=True,
            )
        )
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_mech2_cmd_label_migrated_to_12(self):
        changed = apply_information_bank_unit_label_migrations(self.db)
        self.assertTrue(changed)
        row = self.db.get(InformationBankUnitLevel, "ul_mech2_bn_cmd")
        self.assertIsNotNone(row)
        self.assertEqual(row.label, "قيادة كتيبة المشاة الآلية/12")


if __name__ == "__main__":
    unittest.main()
