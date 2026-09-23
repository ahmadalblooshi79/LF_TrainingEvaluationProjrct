import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.information_bank_catalog import INFO_BANK_UNIT_LEVEL_TEMPLATES
from app.info_bank_tree import _unit_rows
from app.models import InformationBankUnitLevel, InformationBankUnitNote
from app.planning_catalog_sync import purge_builtin_seeded_unit_levels, sync_planning_unit_levels_from_db
from app.unit_levels_catalog import UNIT_LEVELS
from app.views import _ensure_information_bank_catalog_rows, _information_bank_unit_levels


class EmptyOrganizationCatalogTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        UNIT_LEVELS.clear()

    def tearDown(self):
        UNIT_LEVELS.clear()
        self.db.close()

    def test_builtin_templates_are_empty(self):
        self.assertEqual(INFO_BANK_UNIT_LEVEL_TEMPLATES, [])

    def test_ensure_does_not_seed_units(self):
        _ensure_information_bank_catalog_rows(self.db)
        self.assertEqual(self.db.query(InformationBankUnitLevel).count(), 0)
        self.assertEqual(_information_bank_unit_levels(self.db), [])
        self.assertEqual(_unit_rows(self.db), [])

    def test_purge_removes_ul_keys_keeps_user_rows(self):
        self.db.add(
            InformationBankUnitLevel(
                key="ul_medical",
                label="السرية الطبية",
                brigade_group="1",
                sort_order=0,
                is_system=True,
                included_in_exercise=True,
            )
        )
        self.db.add(
            InformationBankUnitNote(unit_level_key="ul_medical", notes="قديم")
        )
        self.db.add(
            InformationBankUnitLevel(
                key="unit_bg1_abc123",
                label="مستوى المستخدم",
                brigade_group="1",
                sort_order=1,
                is_system=False,
                included_in_exercise=True,
            )
        )
        self.db.commit()
        removed = purge_builtin_seeded_unit_levels(self.db)
        self.assertEqual(removed, 1)
        self.assertIsNone(
            self.db.query(InformationBankUnitLevel).filter_by(key="ul_medical").first()
        )
        self.assertIsNone(
            self.db.query(InformationBankUnitNote)
            .filter_by(unit_level_key="ul_medical")
            .first()
        )
        kept = (
            self.db.query(InformationBankUnitLevel)
            .filter_by(key="unit_bg1_abc123")
            .first()
        )
        self.assertIsNotNone(kept)
        sync_planning_unit_levels_from_db(self.db)
        self.assertEqual([u["key"] for u in UNIT_LEVELS], ["unit_bg1_abc123"])


if __name__ == "__main__":
    unittest.main()
