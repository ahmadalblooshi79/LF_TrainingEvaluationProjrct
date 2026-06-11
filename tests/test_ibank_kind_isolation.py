import unittest
import unittest.mock

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.action_eval_ibank_sync import (
    INFO_BANK_ACTION_EVAL_KIND,
    collect_ibank_action_eval_files_for_phase_unit,
)
from app.database import Base
from app.evaluation_list_ibank_sync import (
    INFO_BANK_EVAL_LIST_KIND,
    collect_ibank_eval_files_for_phase_unit,
)
from app.models import InformationBankTreeNode, InformationBankTrainingPhase, InformationBankUnitLevel


class IbankKindIsolationTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        self.db.add(
            InformationBankTrainingPhase(
                key="preparation",
                label="التحضير",
                included_in_exercise=True,
            )
        )
        self.db.add(
            InformationBankUnitLevel(
                key="ul_mech13_bn_c1",
                label="السرية 1",
                included_in_exercise=True,
            )
        )
        self.db.commit()
        self.phase_eval = InformationBankTreeNode(
            kind=INFO_BANK_EVAL_LIST_KIND,
            parent_id=None,
            name="التحضير",
            is_folder=True,
            catalog_phase_key="preparation",
            is_system=True,
        )
        self.phase_action = InformationBankTreeNode(
            kind=INFO_BANK_ACTION_EVAL_KIND,
            parent_id=None,
            name="التحضير",
            is_folder=True,
            catalog_phase_key="preparation",
            is_system=True,
        )
        self.db.add(self.phase_eval)
        self.db.add(self.phase_action)
        self.db.flush()
        self.unit_eval = InformationBankTreeNode(
            kind=INFO_BANK_EVAL_LIST_KIND,
            parent_id=int(self.phase_eval.id),
            name="السرية 1",
            is_folder=True,
            catalog_unit_key="ul_mech13_bn_c1",
        )
        self.unit_action = InformationBankTreeNode(
            kind=INFO_BANK_ACTION_EVAL_KIND,
            parent_id=int(self.phase_action.id),
            name="السرية 1",
            is_folder=True,
            catalog_unit_key="ul_mech13_bn_c1",
        )
        self.db.add(self.unit_eval)
        self.db.add(self.unit_action)
        self.db.flush()
        self.file_eval = InformationBankTreeNode(
            kind=INFO_BANK_EVAL_LIST_KIND,
            parent_id=int(self.unit_eval.id),
            name="eval.xlsx",
            is_folder=False,
            file_relpath="dilemma_eval/tree/n1/eval.xlsx",
            catalog_unit_key="ul_mech13_bn_c1",
        )
        self.file_action = InformationBankTreeNode(
            kind=INFO_BANK_ACTION_EVAL_KIND,
            parent_id=int(self.unit_action.id),
            name="action.xlsx",
            is_folder=False,
            file_relpath="action_eval/tree/n2/action.xlsx",
            catalog_unit_key="ul_mech13_bn_c1",
        )
        self.db.add(self.file_eval)
        self.db.add(self.file_action)
        self.db.commit()

    def test_eval_collect_ignores_action_eval_tab(self):
        with (
            unittest.mock.patch(
                "app.evaluation_list_ibank_sync.prepare_dilemma_eval_ibank_tree"
            ),
            unittest.mock.patch(
                "app.evaluation_list_ibank_sync._file_node_to_source",
                return_value={
                    "node_id": int(self.file_eval.id),
                    "title": "eval",
                    "src_relpath": "dilemma_eval/tree/n1/eval.xlsx",
                    "sort_order": 0,
                },
            ),
        ):
            sources = collect_ibank_eval_files_for_phase_unit(
                self.db,
                phase_key="preparation",
                unit_key="ul_mech13_bn_c1",
            )
        node_ids = {int(s["node_id"]) for s in sources}
        self.assertIn(int(self.file_eval.id), node_ids)
        self.assertNotIn(int(self.file_action.id), node_ids)

    def test_action_collect_ignores_eval_tab(self):
        with (
            unittest.mock.patch(
                "app.action_eval_ibank_sync.prepare_action_eval_ibank_tree"
            ),
            unittest.mock.patch(
                "app.action_eval_ibank_sync._file_node_to_source",
                return_value={
                    "node_id": int(self.file_action.id),
                    "title": "action",
                    "src_relpath": "action_eval/tree/n2/action.xlsx",
                    "sort_order": 0,
                },
            ),
        ):
            sources = collect_ibank_action_eval_files_for_phase_unit(
                self.db,
                phase_key="preparation",
                unit_key="ul_mech13_bn_c1",
            )
        node_ids = {int(s["node_id"]) for s in sources}
        self.assertIn(int(self.file_action.id), node_ids)
        self.assertNotIn(int(self.file_eval.id), node_ids)


if __name__ == "__main__":
    unittest.main()
