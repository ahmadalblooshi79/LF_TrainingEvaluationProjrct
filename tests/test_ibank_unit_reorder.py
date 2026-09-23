import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.ibank_unit_order import apply_information_bank_unit_order
from app.models import InformationBankUnitLevel
from app.views import _ensure_information_bank_catalog_rows


class IbankUnitReorderTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        for i, (key, label) in enumerate(
            (("unit_a", "وحدة أ"), ("unit_b", "وحدة ب"), ("unit_c", "وحدة ج"))
        ):
            self.db.add(
                InformationBankUnitLevel(
                    key=key,
                    label=label,
                    brigade_group="1",
                    sort_order=i,
                    is_system=True,
                )
            )
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def _keys(self):
        rows = (
            self.db.query(InformationBankUnitLevel)
            .filter(InformationBankUnitLevel.brigade_group == "1")
            .order_by(
                InformationBankUnitLevel.sort_order,
                InformationBankUnitLevel.created_at,
                InformationBankUnitLevel.key,
            )
            .all()
        )
        return [r.key for r in rows]

    def test_apply_order_moves_row_to_top(self):
        keys = apply_information_bank_unit_order(
            self.db, ordered_keys=["unit_c", "unit_a", "unit_b"]
        )
        self.db.commit()
        self.assertEqual(keys, ["unit_c", "unit_a", "unit_b"])
        self.assertEqual(self._keys(), ["unit_c", "unit_a", "unit_b"])

    def test_apply_order_appends_missing_keys(self):
        keys = apply_information_bank_unit_order(self.db, ordered_keys=["unit_b"])
        self.db.commit()
        self.assertEqual(keys[0], "unit_b")
        self.assertEqual(set(keys), {"unit_a", "unit_b", "unit_c"})
        self.assertEqual(self._keys()[0], "unit_b")

    def test_empty_order_raises(self):
        with self.assertRaises(ValueError):
            apply_information_bank_unit_order(self.db, ordered_keys=[])

    def test_unknown_first_key_raises(self):
        with self.assertRaises(ValueError):
            apply_information_bank_unit_order(self.db, ordered_keys=["missing"])

    def test_ensure_does_not_reset_custom_order(self):
        apply_information_bank_unit_order(self.db, ordered_keys=["unit_b", "unit_a", "unit_c"])
        self.db.commit()
        _ensure_information_bank_catalog_rows(self.db)
        orders = {
            r.key: r.sort_order
            for r in self.db.query(InformationBankUnitLevel)
            .filter(InformationBankUnitLevel.key.in_(["unit_a", "unit_b", "unit_c"]))
            .all()
        }
        self.assertEqual(orders, {"unit_b": 0, "unit_a": 1, "unit_c": 2})

    def test_ensure_does_not_recreate_builtin_seeded_row(self):
        self.db.add(
            InformationBankUnitLevel(
                key="ul_brigade_grp_cmd",
                label="قيادة مجموعة اللواء",
                brigade_group="1",
                sort_order=99,
                is_system=True,
            )
        )
        self.db.commit()
        _ensure_information_bank_catalog_rows(self.db)
        self.assertIsNone(
            self.db.query(InformationBankUnitLevel)
            .filter_by(key="ul_brigade_grp_cmd")
            .first()
        )

    def test_ensure_keeps_user_added_row(self):
        self.db.add(
            InformationBankUnitLevel(
                key="unit_bg1_custom1",
                label="مستوى مستخدم",
                brigade_group="1",
                sort_order=99,
                is_system=False,
            )
        )
        self.db.commit()
        _ensure_information_bank_catalog_rows(self.db)
        row = (
            self.db.query(InformationBankUnitLevel)
            .filter_by(key="unit_bg1_custom1")
            .first()
        )
        self.assertIsNotNone(row)
        self.assertEqual(row.sort_order, 99)
        self.assertFalse(row.is_system)


if __name__ == "__main__":
    unittest.main()
