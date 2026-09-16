import unittest
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.action_eval_ibank_sync import (
    delete_published_action_eval_slot,
    publish_action_eval_lists_from_ibank,
    withdraw_action_eval_for_units_removed_from_flow,
)
from app.database import Base
from app.evaluation_list_ibank_sync import (
    delete_published_evaluation_list_item,
    prune_ibank_evaluation_lists_not_in_roster,
    sync_evaluation_lists_from_ibank,
)
from app.models import (
    EvaluationListPdfItem,
    EvaluationListSavedResult,
    ExercisePlannerFlowBundle,
    ExercisePlannerFlowBundleActionEval,
    PlannerFlowBundleEvalSavedResult,
    RoleKey,
    User,
)
from app.permissions import is_system_admin


class EvalListWithdrawKeepResultsTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()

    def tearDown(self):
        self.db.close()

    def _add_item(self, *, node_id: int, text: str = "قائمة") -> EvaluationListPdfItem:
        item = EvaluationListPdfItem(
            exercise_id=1,
            exercise_phase="preparation",
            unit_level_key="ul_mech2_bn_c1",
            unit_level_label="سرية",
            sort_order=0,
            text=text,
            pdf_relpath=f"ul_mech2_bn_c1/ibn_{int(node_id)}.xlsx",
        )
        self.db.add(item)
        self.db.flush()
        return item

    def test_withdraw_keeps_item_with_saved_result(self):
        item = self._add_item(node_id=9)
        self.db.add(
            EvaluationListSavedResult(
                evaluation_item_id=int(item.id),
                exercise_id=1,
                exercise_phase="preparation",
                unit_level_key="ul_mech2_bn_c1",
                payload_json="{}",
                total_pct=70.0,
                is_approved=False,
            )
        )
        self.db.flush()
        stats = sync_evaluation_lists_from_ibank(
            self.db,
            exercise_id=1,
            phase_key="preparation",
            unit_key="ul_mech2_bn_c1",
            unit_label="سرية",
            sources=[],
            allow_remove=True,
        )
        self.db.flush()
        self.assertEqual(int(stats.get("removed") or 0), 0)
        self.assertGreaterEqual(int(stats.get("skipped_with_results") or 0), 1)
        self.assertIsNotNone(self.db.get(EvaluationListPdfItem, int(item.id)))
        self.assertIsNotNone(
            self.db.query(EvaluationListSavedResult)
            .filter(EvaluationListSavedResult.evaluation_item_id == int(item.id))
            .first()
        )

    def test_withdraw_removes_unused_item(self):
        item = self._add_item(node_id=11)
        stats = sync_evaluation_lists_from_ibank(
            self.db,
            exercise_id=1,
            phase_key="preparation",
            unit_key="ul_mech2_bn_c1",
            unit_label="سرية",
            sources=[],
            allow_remove=True,
        )
        self.db.flush()
        self.assertEqual(int(stats.get("removed") or 0), 1)
        self.assertIsNone(self.db.get(EvaluationListPdfItem, int(item.id)))

    def test_sync_without_allow_remove_does_not_delete_unused(self):
        item = self._add_item(node_id=12)
        stats = sync_evaluation_lists_from_ibank(
            self.db,
            exercise_id=1,
            phase_key="preparation",
            unit_key="ul_mech2_bn_c1",
            unit_label="سرية",
            sources=[],
        )
        self.db.flush()
        self.assertEqual(int(stats.get("removed") or 0), 0)
        self.assertIsNotNone(self.db.get(EvaluationListPdfItem, int(item.id)))

    def test_prune_roster_is_noop(self):
        item = self._add_item(node_id=13)
        removed = prune_ibank_evaluation_lists_not_in_roster(
            self.db, exercise_id=1, active_unit_keys=set()
        )
        self.assertEqual(removed, 0)
        self.assertIsNotNone(self.db.get(EvaluationListPdfItem, int(item.id)))

    def test_admin_delete_removes_item_and_result(self):
        item = self._add_item(node_id=14)
        self.db.add(
            EvaluationListSavedResult(
                evaluation_item_id=int(item.id),
                exercise_id=1,
                exercise_phase="preparation",
                unit_level_key="ul_mech2_bn_c1",
                payload_json="{}",
                is_approved=True,
                is_chief_approved=True,
            )
        )
        self.db.flush()
        item_id = int(item.id)
        ok = delete_published_evaluation_list_item(
            self.db, exercise_id=1, item_id=item_id
        )
        self.db.flush()
        self.assertTrue(ok)
        self.assertIsNone(self.db.get(EvaluationListPdfItem, item_id))
        self.assertIsNone(
            self.db.query(EvaluationListSavedResult)
            .filter(EvaluationListSavedResult.evaluation_item_id == item_id)
            .first()
        )


class ActionEvalWithdrawKeepResultsTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        self.bundle = ExercisePlannerFlowBundle(
            exercise_id=1,
            exercise_phase="preparation",
            unit_level_key="ul_brigade_grp_cmd",
            unit_level_label="قيادة",
        )
        self.db.add(self.bundle)
        self.db.flush()

    def tearDown(self):
        self.db.close()

    def _add_slot(self, *, node_id: int) -> ExercisePlannerFlowBundleActionEval:
        slot = ExercisePlannerFlowBundleActionEval(
            bundle_id=int(self.bundle.id),
            slot_index=1,
            title="قائمة معضلة",
            file_relpath=f"{int(self.bundle.id)}/ibn_{int(node_id)}.xlsx",
        )
        self.db.add(slot)
        self.db.flush()
        return slot

    def test_withdraw_keeps_slot_with_saved_result(self):
        slot = self._add_slot(node_id=21)
        self.db.add(
            PlannerFlowBundleEvalSavedResult(
                bundle_action_eval_id=int(slot.id),
                exercise_id=1,
                exercise_phase="preparation",
                unit_level_key="ul_brigade_grp_cmd",
                payload_json="{}",
                total_pct=55.0,
                is_approved=False,
            )
        )
        self.db.flush()
        stats = publish_action_eval_lists_from_ibank(
            self.db,
            exercise_id=1,
            phase_key="preparation",
            unit_key="ul_brigade_grp_cmd",
            selected_node_ids=set(),
            allow_remove=True,
        )
        self.db.flush()
        self.assertEqual(int(stats.get("removed") or 0), 0)
        self.assertGreaterEqual(int(stats.get("skipped_with_results") or 0), 1)
        self.assertIsNotNone(self.db.get(ExercisePlannerFlowBundleActionEval, int(slot.id)))

    def test_flow_unit_removal_does_not_auto_withdraw(self):
        slot = self._add_slot(node_id=22)
        withdrawn = withdraw_action_eval_for_units_removed_from_flow(
            self.db, exercise_id=1, phase_key="preparation"
        )
        self.assertEqual(withdrawn, 0)
        self.assertIsNotNone(self.db.get(ExercisePlannerFlowBundleActionEval, int(slot.id)))

    def test_admin_delete_removes_slot_and_result(self):
        slot = self._add_slot(node_id=23)
        self.db.add(
            PlannerFlowBundleEvalSavedResult(
                bundle_action_eval_id=int(slot.id),
                exercise_id=1,
                exercise_phase="preparation",
                unit_level_key="ul_brigade_grp_cmd",
                payload_json="{}",
                is_approved=True,
                is_chief_approved=True,
            )
        )
        self.db.flush()
        slot_id = int(slot.id)
        ok = delete_published_action_eval_slot(
            self.db, exercise_id=1, slot_id=slot_id
        )
        self.db.flush()
        self.assertTrue(ok)
        self.assertIsNone(self.db.get(ExercisePlannerFlowBundleActionEval, slot_id))
        self.assertIsNone(
            self.db.query(PlannerFlowBundleEvalSavedResult)
            .filter(PlannerFlowBundleEvalSavedResult.bundle_action_eval_id == slot_id)
            .first()
        )


class AdminDeleteRoutePermissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from app import create_app

        cls.app = create_app()
        cls.app.config["TESTING"] = True

    def _user(self, role: str) -> User:
        u = MagicMock(spec=User)
        u.role_key = role
        u.id = 1
        return u

    def test_judge_forbidden_eval_list_delete(self):
        with patch("app.views.get_current_user_optional", return_value=self._user(RoleKey.JUDGE.value)):
            client = self.app.test_client()
            resp = client.post("/admin/published-eval-lists/1/delete")
            self.assertEqual(resp.status_code, 403)

    def test_judge_forbidden_action_eval_delete(self):
        with patch("app.views.get_current_user_optional", return_value=self._user(RoleKey.JUDGE.value)):
            client = self.app.test_client()
            resp = client.post("/admin/published-action-eval/1/delete")
            self.assertEqual(resp.status_code, 403)

    def test_system_admin_role_is_admin(self):
        self.assertTrue(is_system_admin(self._user(RoleKey.SYSTEM_ADMIN.value)))
        self.assertFalse(is_system_admin(self._user(RoleKey.JUDGE.value)))
        self.assertFalse(is_system_admin(self._user(RoleKey.PLANNER.value)))

    @classmethod
    def tearDownClass(cls):
        from app.info_bank_tree import invalidate_information_bank_kind_cache

        invalidate_information_bank_kind_cache()
