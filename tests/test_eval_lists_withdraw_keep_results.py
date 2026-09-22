import unittest
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.action_eval_ibank_sync import (
    delete_published_action_eval_slot,
    publish_action_eval_lists_from_ibank,
    withdraw_action_eval_for_units_removed_from_flow,
    withdraw_all_action_eval_for_day,
)
from app.database import Base
from app.evaluation_list_ibank_sync import (
    delete_published_evaluation_list_item,
    prune_ibank_evaluation_lists_not_in_roster,
    sync_evaluation_lists_from_ibank,
    withdraw_all_evaluation_lists_for_phase,
)
from app.models import (
    EvaluationListPdfItem,
    EvaluationListSavedResult,
    ExercisePlannerFlowBundle,
    ExercisePlannerFlowBundleActionEval,
    InformationBankTreeNode,
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

    def test_withdraw_unselected_keeps_checked_and_drops_unchecked(self):
        keep = self._add_item(node_id=31, text="تبقى")
        drop = self._add_item(node_id=32, text="تُسحب")
        stats = withdraw_all_evaluation_lists_for_phase(
            self.db,
            exercise_id=1,
            phase_key="preparation",
            keep_by_unit={"ul_mech2_bn_c1": {31}},
        )
        self.db.flush()
        self.assertEqual(int(stats.get("removed") or 0), 1)
        self.assertIsNotNone(self.db.get(EvaluationListPdfItem, int(keep.id)))
        self.assertIsNone(self.db.get(EvaluationListPdfItem, int(drop.id)))

    def test_withdraw_unselected_keeps_unchecked_item_with_results(self):
        keep = self._add_item(node_id=33, text="تبقى")
        blocked = self._add_item(node_id=34, text="نتائج")
        self.db.add(
            EvaluationListSavedResult(
                evaluation_item_id=int(blocked.id),
                exercise_id=1,
                exercise_phase="preparation",
                unit_level_key="ul_mech2_bn_c1",
                payload_json="{}",
            )
        )
        self.db.flush()
        stats = withdraw_all_evaluation_lists_for_phase(
            self.db,
            exercise_id=1,
            phase_key="preparation",
            keep_by_unit={"ul_mech2_bn_c1": {33}},
        )
        self.db.flush()
        self.assertEqual(int(stats.get("removed") or 0), 0)
        self.assertGreaterEqual(int(stats.get("skipped_with_results") or 0), 1)
        self.assertIsNotNone(self.db.get(EvaluationListPdfItem, int(keep.id)))
        self.assertIsNotNone(self.db.get(EvaluationListPdfItem, int(blocked.id)))

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

    def _add_slot(self, *, node_id: int, slot_index: int = 1) -> ExercisePlannerFlowBundleActionEval:
        slot = ExercisePlannerFlowBundleActionEval(
            bundle_id=int(self.bundle.id),
            slot_index=int(slot_index),
            title="قائمة معضلة",
            file_relpath=f"{int(self.bundle.id)}/ibn_{int(node_id)}.xlsx",
        )
        self.db.add(slot)
        self.db.flush()
        return slot

    def _add_tree_file(self, node_id: int) -> None:
        self.db.add(
            InformationBankTreeNode(
                id=int(node_id),
                kind="action_eval",
                name=f"list {node_id}",
                is_folder=False,
                catalog_unit_key="ul_brigade_grp_cmd",
            )
        )
        self.db.flush()

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

    def test_withdraw_unselected_keeps_checked_and_drops_unchecked(self):
        self._add_tree_file(41)
        self._add_tree_file(42)
        keep = self._add_slot(node_id=41, slot_index=1)
        drop = self._add_slot(node_id=42, slot_index=2)
        stats = publish_action_eval_lists_from_ibank(
            self.db,
            exercise_id=1,
            phase_key="preparation",
            unit_key="ul_brigade_grp_cmd",
            selected_node_ids={41},
            allow_remove=True,
            withdraw_only=True,
        )
        self.db.flush()
        self.assertEqual(int(stats.get("removed") or 0), 1)
        self.assertIsNotNone(self.db.get(ExercisePlannerFlowBundleActionEval, int(keep.id)))
        self.assertIsNone(self.db.get(ExercisePlannerFlowBundleActionEval, int(drop.id)))

    def test_withdraw_all_for_day_honors_keep_by_unit(self):
        self._add_tree_file(51)
        self._add_tree_file(52)
        keep = self._add_slot(node_id=51, slot_index=1)
        drop = self._add_slot(node_id=52, slot_index=2)
        stats = withdraw_all_action_eval_for_day(
            self.db,
            exercise_id=1,
            phase_key="preparation",
            flow_day_id="",
            keep_by_unit={"ul_brigade_grp_cmd": {51}},
        )
        self.db.flush()
        self.assertEqual(int(stats.get("removed") or 0), 1)
        self.assertIsNotNone(self.db.get(ExercisePlannerFlowBundleActionEval, int(keep.id)))
        self.assertIsNone(self.db.get(ExercisePlannerFlowBundleActionEval, int(drop.id)))


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
