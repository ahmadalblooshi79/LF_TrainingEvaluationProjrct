import json
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.info_bank_tree import (
    ensure_information_bank_kind,
    flow_day_catalog_key,
    ibank_event_flow_days,
)
from app.models import InformationBankEventFlowTable, InformationBankTreeNode


class IbankActionEvalFlowDayTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()

    def test_ensure_action_eval_tree_uses_flow_days(self):
        self.db.add(
            InformationBankEventFlowTable(
                flow_table_json=json.dumps(
                    {
                        "version": 2,
                        "active_day_id": "day-1",
                        "days": [
                            {"id": "day-1", "label": "اليوم/1", "note": "", "rows": []},
                            {"id": "day-2", "label": "اليوم/2", "note": "", "rows": []},
                        ],
                    },
                    ensure_ascii=False,
                )
            )
        )
        self.db.commit()

        ensure_information_bank_kind(self.db, "action_eval")

        roots = (
            self.db.query(InformationBankTreeNode)
            .filter(
                InformationBankTreeNode.kind == "action_eval",
                InformationBankTreeNode.parent_id.is_(None),
            )
            .order_by(InformationBankTreeNode.sort_order)
            .all()
        )
        self.assertEqual(len(roots), 2)
        self.assertEqual(roots[0].catalog_phase_key, flow_day_catalog_key("day-1"))
        self.assertEqual(roots[0].name, "اليوم/1")
        self.assertEqual(roots[1].catalog_phase_key, flow_day_catalog_key("day-2"))
        self.assertEqual(roots[1].name, "اليوم/2")

    def test_new_flow_day_added_on_resync(self):
        self.db.add(
            InformationBankEventFlowTable(
                flow_table_json=json.dumps(
                    {
                        "version": 2,
                        "active_day_id": "day-1",
                        "days": [
                            {"id": "day-1", "label": "اليوم/1", "note": "", "rows": []},
                        ],
                    },
                    ensure_ascii=False,
                )
            )
        )
        self.db.commit()
        ensure_information_bank_kind(self.db, "action_eval")

        row = self.db.query(InformationBankEventFlowTable).first()
        row.flow_table_json = json.dumps(
            {
                "version": 2,
                "active_day_id": "day-1",
                "days": [
                    {"id": "day-1", "label": "اليوم/1", "note": "", "rows": []},
                    {"id": "day-3", "label": "اليوم/3", "note": "", "rows": []},
                ],
            },
            ensure_ascii=False,
        )
        self.db.commit()
        ensure_information_bank_kind(self.db, "action_eval")

        days = ibank_event_flow_days(self.db)
        self.assertEqual(len(days), 2)
        root_keys = {
            n.catalog_phase_key
            for n in self.db.query(InformationBankTreeNode)
            .filter(
                InformationBankTreeNode.kind == "action_eval",
                InformationBankTreeNode.parent_id.is_(None),
            )
            .all()
        }
        self.assertIn(flow_day_catalog_key("day-3"), root_keys)


if __name__ == "__main__":
    unittest.main()
