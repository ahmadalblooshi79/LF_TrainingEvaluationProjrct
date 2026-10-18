"""Phase D: Device Manager reopen/export reuse existing chief-judge authority."""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.models.user import RoleKey
from app.permissions import can_chief_reopen_evaluation_for_judge


def _user(role: str, user_id: int = 1):
    u = MagicMock()
    u.role_key = role
    u.id = user_id
    u.is_active = True
    u.username = f"user{user_id}"
    return u


class DeviceEvalReopenPermissionTests(unittest.TestCase):
    def test_admin_and_chief_can_reopen(self):
        self.assertTrue(
            can_chief_reopen_evaluation_for_judge(_user(RoleKey.SYSTEM_ADMIN.value))
        )
        self.assertTrue(
            can_chief_reopen_evaluation_for_judge(_user(RoleKey.CHIEF_JUDGE.value))
        )

    def test_normal_judge_cannot_reopen(self):
        self.assertFalse(
            can_chief_reopen_evaluation_for_judge(_user(RoleKey.JUDGE.value))
        )

    def test_planner_and_control_cannot_reopen(self):
        self.assertFalse(
            can_chief_reopen_evaluation_for_judge(_user(RoleKey.PLANNER.value))
        )
        self.assertFalse(
            can_chief_reopen_evaluation_for_judge(_user(RoleKey.CONTROL.value))
        )


class DeviceEvalReopenRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from app import create_app

        cls.app = create_app()
        cls.app.config["TESTING"] = True

    def test_reopen_requires_login(self):
        client = self.app.test_client()
        resp = client.post("/api/tablet/device/eval/chief-reopen", json={})
        self.assertEqual(resp.status_code, 401)

    @patch("app.tablet_api.get_current_user_optional")
    def test_reopen_requires_device_setup(self, mock_user):
        mock_user.return_value = _user(RoleKey.SYSTEM_ADMIN.value)
        client = self.app.test_client()
        resp = client.post(
            "/api/tablet/device/eval/chief-reopen",
            json={"kind": "procedure", "judge_id": 9, "item_id": 1},
        )
        self.assertEqual(resp.status_code, 403)

    @patch("app.tablet_api.get_current_user_optional")
    def test_unauthorized_role_blocked_even_with_device_setup(self, mock_user):
        mock_user.return_value = _user(RoleKey.PLANNER.value)
        client = self.app.test_client()
        with client.session_transaction() as sess:
            sess["device_setup"] = True
        resp = client.post(
            "/api/tablet/device/eval/chief-reopen",
            json={"kind": "procedure", "judge_id": 9, "item_id": 1},
        )
        self.assertEqual(resp.status_code, 403)

    def test_authorized_reopen_uses_existing_apply(self):
        from flask import g

        from app.tablet_api import tablet_device_eval_chief_reopen

        admin = _user(RoleKey.SYSTEM_ADMIN.value, 1)
        judge = _user(RoleKey.JUDGE.value, 9)
        item = SimpleNamespace(
            id=44,
            exercise_id=7,
            unit_level_key="snipers",
            text="قائمة الرماية",
        )
        saved = SimpleNamespace(saved_by_id=9)
        ex = SimpleNamespace(id=7)
        db = MagicMock()
        db.get.return_value = item

        with self.app.test_request_context(
            "/api/tablet/device/eval/chief-reopen",
            method="POST",
            json={
                "kind": "procedure",
                "judge_id": 9,
                "exercise_id": 7,
                "unit_key": "snipers",
                "item_id": 44,
            },
        ), patch(
            "app.tablet_api._require_device_setup_user", return_value=(admin, None)
        ), patch(
            "app.tablet_api._provision_judge_user", return_value=(judge, None)
        ), patch(
            "app.tablet_api._device_current_exercise", return_value=ex
        ), patch(
            "app.tablet_api.label_for_unit_level_key", return_value="القناصة"
        ), patch(
            "app.evaluation_workflow.eval_chief_can_reopen", return_value=True
        ), patch(
            "app.evaluation_workflow.apply_chief_reopen"
        ) as apply_reopen, patch(
            "app.views._evaluation_canonical_saved_row", return_value=saved
        ), patch(
            "app.views._eval_list_viewer_ctx",
            return_value={
                "eval_can_edit": True,
                "show_eval_approve": False,
                "saved_is_approved": True,
                "eval_workflow_label": "معاد للتقييم",
            },
        ), patch(
            "app.notifications_service.notify_evaluation_reopened_by_chief_judge"
        ):
            g.db = db
            resp = tablet_device_eval_chief_reopen()
            body = resp.get_json()
            self.assertTrue(body["ok"])
            self.assertEqual(body["judge_id"], 9)
            self.assertEqual(body["item_id"], 44)
            self.assertEqual(body["exercise_id"], 7)
            apply_reopen.assert_called_once_with(saved)

    def test_export_routes_exist(self):
        rules = {str(r) for r in self.app.url_map.iter_rules()}
        self.assertTrue(
            any("export.xlsx" in r and "evaluation-lists" in r for r in rules)
        )
        self.assertTrue(any("export.xlsx" in r and "action-eval" in r for r in rules))
        self.assertTrue(any("device/eval/chief-reopen" in r for r in rules))


if __name__ == "__main__":
    unittest.main()
