import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.ibank_phase_order import apply_information_bank_phase_order, ordered_training_phases
from app.models import InformationBankTrainingPhase, InformationBankTreeNode
from app.views import _ensure_information_bank_catalog_rows


class IbankPhaseReorderTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        for i, (key, label) in enumerate(
            (("phase_a", "مرحلة أ"), ("phase_b", "مرحلة ب"), ("phase_c", "مرحلة ج"))
        ):
            self.db.add(
                InformationBankTrainingPhase(
                    key=key,
                    label=label,
                    sort_order=i,
                    is_system=False,
                )
            )
            self.db.add(
                InformationBankTreeNode(
                    kind="dilemma_eval",
                    parent_id=None,
                    name=label,
                    is_folder=True,
                    catalog_phase_key=key,
                    sort_order=i,
                    is_system=False,
                )
            )
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def _keys(self):
        return [r.key for r in ordered_training_phases(self.db)]

    def test_apply_order_moves_row_to_top(self):
        keys = apply_information_bank_phase_order(
            self.db, ordered_keys=["phase_c", "phase_a", "phase_b"]
        )
        self.db.commit()
        self.assertEqual(keys, ["phase_c", "phase_a", "phase_b"])
        self.assertEqual(self._keys(), ["phase_c", "phase_a", "phase_b"])
        folder_order = [
            r.catalog_phase_key
            for r in self.db.query(InformationBankTreeNode)
            .filter(InformationBankTreeNode.parent_id.is_(None))
            .order_by(InformationBankTreeNode.sort_order)
            .all()
        ]
        self.assertEqual(folder_order, ["phase_c", "phase_a", "phase_b"])

    def test_apply_order_appends_missing_keys(self):
        keys = apply_information_bank_phase_order(self.db, ordered_keys=["phase_b"])
        self.db.commit()
        self.assertEqual(keys[0], "phase_b")
        self.assertEqual(set(keys), {"phase_a", "phase_b", "phase_c"})
        self.assertEqual(self._keys()[0], "phase_b")

    def test_empty_order_raises(self):
        with self.assertRaises(ValueError):
            apply_information_bank_phase_order(self.db, ordered_keys=[])

    def test_unknown_first_key_raises(self):
        with self.assertRaises(ValueError):
            apply_information_bank_phase_order(self.db, ordered_keys=["missing"])

    def test_ensure_does_not_reset_custom_order(self):
        apply_information_bank_phase_order(
            self.db, ordered_keys=["phase_b", "phase_a", "phase_c"]
        )
        self.db.commit()
        _ensure_information_bank_catalog_rows(self.db)
        orders = {
            r.key: r.sort_order
            for r in self.db.query(InformationBankTrainingPhase)
            .filter(InformationBankTrainingPhase.key.in_(["phase_a", "phase_b", "phase_c"]))
            .all()
        }
        self.assertEqual(orders, {"phase_b": 0, "phase_a": 1, "phase_c": 2})

    def test_rename_updates_root_folder_name(self):
        row = (
            self.db.query(InformationBankTrainingPhase)
            .filter_by(key="phase_b")
            .first()
        )
        row.label = "مرحلة مصححة"
        row.is_system = False
        for node in (
            self.db.query(InformationBankTreeNode)
            .filter(
                InformationBankTreeNode.catalog_phase_key == "phase_b",
                InformationBankTreeNode.is_folder.is_(True),
                InformationBankTreeNode.parent_id.is_(None),
            )
            .all()
        ):
            node.name = "مرحلة مصححة"
        self.db.commit()
        folder = (
            self.db.query(InformationBankTreeNode)
            .filter_by(catalog_phase_key="phase_b")
            .first()
        )
        self.assertEqual(folder.name, "مرحلة مصححة")
        self.assertEqual(
            self.db.query(InformationBankTrainingPhase)
            .filter_by(key="phase_b")
            .first()
            .label,
            "مرحلة مصححة",
        )


if __name__ == "__main__":
    unittest.main()
