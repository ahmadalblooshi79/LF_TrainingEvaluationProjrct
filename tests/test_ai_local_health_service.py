"""اختبارات فحص الصحة والهياكل المبدئية للمزودين."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.ai_local_engine.models import AiSettings
from app.ai_local_engine.providers.llamacpp_provider import LlamaCppProvider
from app.ai_local_engine.providers.lmstudio_provider import LMStudioProvider
from app.ai_local_engine.schemas.response_schema import UnifiedAIResponse
from app.ai_local_engine.services.ai_service import ensure_default_settings
from app.ai_local_engine.services.health_service import HealthService
from app.database import Base


class HealthServiceTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine, tables=[AiSettings.__table__])
        Session = sessionmaker(bind=engine)
        self.db = Session()
        ensure_default_settings(self.db)

    def tearDown(self):
        self.db.close()

    @patch("app.ai_local_engine.providers.ollama_provider.OllamaProvider.health_check")
    def test_health_when_ollama_down_system_ok(self, mock_health):
        mock_health.return_value = {
            "server_reachable": False,
            "model_available": False,
            "model_responding": False,
            "response_time": 0.01,
            "last_error": "تعذر الاتصال بخدمة Ollama. تأكد من تشغيل Ollama ومن صحة عنوان الخادم المحلي.",
            "provider": "ollama",
        }
        status = HealthService(self.db).check(probe_model=True)
        self.assertTrue(status.ai_enabled)
        self.assertFalse(status.server_reachable)
        self.assertIsNotNone(status.last_error)

    def test_lmstudio_stub(self):
        p = LMStudioProvider(base_url="http://127.0.0.1:1234")
        r = p.test_connection()
        self.assertFalse(r.success)
        self.assertEqual(r.error_code, "provider_not_ready")

    def test_llamacpp_stub(self):
        p = LlamaCppProvider(base_url="http://127.0.0.1:8080")
        r = p.test_connection()
        self.assertIsInstance(r, UnifiedAIResponse)
        self.assertFalse(r.success)


if __name__ == "__main__":
    unittest.main()
