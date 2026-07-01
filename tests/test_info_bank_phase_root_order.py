"""اختبار: ترتيب مجلدات المراحل في الجذر لا يتأثر بالترتيب الطبيعي."""
from __future__ import annotations

import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.info_bank_tree import (
    _resort_siblings_by_natural_name,
    repair_tree_natural_sibling_order,
)
from app.models import InformationBankTreeNode

KIND = "dilemma_eval"


class PhaseRootOrderProtectionTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        self.phases = []
        for i, (key, name) in enumerate(
            (
                ("opening", "مرحلة الإنفتاح"),
                ("preparation", "مرحلة التحضير"),
                ("battle_exposure", "مرحلة المعركة التعرضية"),
                ("reorganization", "مرحلة مسارات التقييم"),
            )
        ):
            row = InformationBankTreeNode(
                kind=KIND,
                parent_id=None,
                name=name,
                is_folder=True,
                catalog_phase_key=key,
                sort_order=i,
                is_system=True,
            )
            self.phases.append(row)
            self.db.add(row)
        self.db.commit()

    def _root_names(self) -> list[str]:
        rows = (
            self.db.query(InformationBankTreeNode)
            .filter(InformationBankTreeNode.parent_id.is_(None))
            .order_by(InformationBankTreeNode.sort_order, InformationBankTreeNode.id)
            .all()
        )
        return [r.name for r in rows]

    def test_resort_skips_tree_root(self):
        self.assertFalse(
            _resort_siblings_by_natural_name(self.db, kind=KIND, parent_id=None)
        )
        repair_tree_natural_sibling_order(self.db, KIND)
        self.db.commit()
        self.assertEqual(
            self._root_names(),
            [
                "مرحلة الإنفتاح",
                "مرحلة التحضير",
                "مرحلة المعركة التعرضية",
                "مرحلة مسارات التقييم",
            ],
        )


if __name__ == "__main__":
    unittest.main()
