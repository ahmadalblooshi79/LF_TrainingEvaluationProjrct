"""اختبارات صلاحيات ومسارات مركز الذكاء الاصطناعي."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from app.models import RoleKey, User
from app.permissions import (
    can_access_ai_center,
    can_edit_ai_settings,
    can_test_ai_connection,
    can_view_ai_models,
)


def _user(role: str) -> User:
    u = MagicMock(spec=User)
    u.role_key = role
    u.id = 1
    return u


class AiLocalPermissionTests(unittest.TestCase):
    def test_admin_can_access(self):
        admin = _user(RoleKey.SYSTEM_ADMIN.value)
        self.assertTrue(can_access_ai_center(admin))
        self.assertTrue(can_edit_ai_settings(admin))
        self.assertTrue(can_test_ai_connection(admin))
        self.assertTrue(can_view_ai_models(admin))

    def test_judge_denied(self):
        judge = _user(RoleKey.JUDGE.value)
        self.assertFalse(can_access_ai_center(judge))
        self.assertFalse(can_edit_ai_settings(judge))
        self.assertFalse(can_test_ai_connection(judge))


class AiLocalRouteSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from app import create_app

        cls.app = create_app()
        cls.app.config["TESTING"] = True

    def test_ai_center_requires_login(self):
        client = self.app.test_client()
        resp = client.get("/ai-center", follow_redirects=False)
        self.assertIn(resp.status_code, (302, 401))

    def test_api_settings_unauthorized(self):
        client = self.app.test_client()
        resp = client.get("/api/ai/settings")
        self.assertEqual(resp.status_code, 401)

    @patch("app.views.get_current_user_optional")
    def test_judge_forbidden_ai_center(self, mock_user):
        mock_user.return_value = _user(RoleKey.JUDGE.value)
        client = self.app.test_client()
        resp = client.get("/ai-center")
        self.assertEqual(resp.status_code, 403)

    @patch("app.views.get_current_user_optional")
    def test_admin_opens_ai_center(self, mock_user):
        mock_user.return_value = _user(RoleKey.SYSTEM_ADMIN.value)
        client = self.app.test_client()
        resp = client.get("/ai-center")
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn("مركز الذكاء الاصطناعي المحلي", html)
        self.assertIn("إعدادات الاتصال", html)

    @patch("app.views.can_access_ai_center", return_value=True)
    @patch("app.views.get_current_user_optional")
    def test_dashboard_contains_ai_card_for_admin(self, mock_user, _perm):
        mock_user.return_value = _user(RoleKey.SYSTEM_ADMIN.value)
        client = self.app.test_client()
        # dashboard builds cards using can_access_ai_center from views import
        with patch("app.views.can_access_ai_center", return_value=True):
            resp = client.get("/dashboard")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("مركز الذكاء الاصطناعي", resp.get_data(as_text=True))
        self.assertIn("/ai-center", resp.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
