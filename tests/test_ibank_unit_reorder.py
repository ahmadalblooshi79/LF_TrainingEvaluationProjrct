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
            (("ul_a", "وحدة أ"), ("ul_b", "وحدة ب"), ("ul_c", "وحدة ج"))
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
            self.db, ordered_keys=["ul_c", "ul_a", "ul_b"]
        )
        self.db.commit()
        self.assertEqual(keys, ["ul_c", "ul_a", "ul_b"])
        self.assertEqual(self._keys(), ["ul_c", "ul_a", "ul_b"])

    def test_apply_order_appends_missing_keys(self):
        keys = apply_information_bank_unit_order(self.db, ordered_keys=["ul_b"])
        self.db.commit()
        self.assertEqual(keys[0], "ul_b")
        self.assertEqual(set(keys), {"ul_a", "ul_b", "ul_c"})
        self.assertEqual(self._keys()[0], "ul_b")

    def test_empty_order_raises(self):
        with self.assertRaises(ValueError):
            apply_information_bank_unit_order(self.db, ordered_keys=[])

    def test_unknown_first_key_raises(self):
        with self.assertRaises(ValueError):
            apply_information_bank_unit_order(self.db, ordered_keys=["missing"])

    def test_ensure_does_not_reset_custom_order(self):
        apply_information_bank_unit_order(self.db, ordered_keys=["ul_b", "ul_a", "ul_c"])
        self.db.commit()
        _ensure_information_bank_catalog_rows(self.db)
        orders = {
            r.key: r.sort_order
            for r in self.db.query(InformationBankUnitLevel)
            .filter(InformationBankUnitLevel.key.in_(["ul_a", "ul_b", "ul_c"]))
            .all()
        }
        self.assertEqual(orders, {"ul_b": 0, "ul_a": 1, "ul_c": 2})

    def test_ensure_keeps_reordered_template_row(self):
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
        self.assertEqual(
            self.db.query(InformationBankUnitLevel)
            .filter_by(key="ul_brigade_grp_cmd")
            .first()
            .sort_order,
            99,
        )


if __name__ == "__main__":
    unittest.main()
