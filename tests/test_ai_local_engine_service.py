"""اختبارات خدمة الذكاء الاصطناعي المحلي والأمان — بدون تشغيل Ollama."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.ai_local_engine.exceptions import (
    AIConfigurationError,
    AIExternalConnectionBlockedError,
    AIProviderDisabledError,
)
from app.ai_local_engine.models import AiSettings
from app.ai_local_engine.schemas.request_schema import GenerateTextRequest
from app.ai_local_engine.schemas.response_schema import UnifiedAIResponse
from app.ai_local_engine.security import validate_ai_base_url
from app.ai_local_engine.services.ai_service import AIService, ensure_default_settings
from app.database import Base


class AiLocalSecurityTests(unittest.TestCase):
    def test_allow_localhost(self):
        self.assertEqual(
            validate_ai_base_url("http://127.0.0.1:11434"),
            "http://127.0.0.1:11434",
        )
        self.assertTrue(validate_ai_base_url("http://localhost:11434").startswith("http://localhost"))

    def test_block_external(self):
        with self.assertRaises(AIExternalConnectionBlockedError):
            validate_ai_base_url("https://api.openai.com/v1")
        with self.assertRaises(AIExternalConnectionBlockedError):
            validate_ai_base_url("http://8.8.8.8:11434")

    def test_allow_private_when_enabled(self):
        url = validate_ai_base_url("http://192.168.1.10:11434", allow_internal_network=True)
        self.assertEqual(url, "http://192.168.1.10:11434")

    def test_block_private_when_disabled(self):
        with self.assertRaises(AIExternalConnectionBlockedError):
            validate_ai_base_url("http://192.168.1.10:11434", allow_internal_network=False)


class AiLocalServiceTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine, tables=[AiSettings.__table__])
        Session = sessionmaker(bind=engine)
        self.db = Session()
        ensure_default_settings(self.db)

    def tearDown(self):
        self.db.close()

    def test_load_and_save_settings(self):
        svc = AIService(self.db)
        s = svc.get_settings()
        self.assertEqual(s.provider, "ollama")
        saved = svc.save_settings(
            {
                "enabled": True,
                "provider": "ollama",
                "base_url": "http://127.0.0.1:11434",
                "model_name": "llama3",
                "temperature": 0.3,
                "max_tokens": 2048,
                "timeout_seconds": 120,
                "retry_count": 1,
                "context_window": 4096,
                "response_language": "ar",
                "structured_output": True,
                "allow_internal_network": False,
            },
            user_id=1,
        )
        self.assertEqual(saved.model_name, "llama3")
        self.assertEqual(saved.temperature, 0.3)

    def test_provider_selection_and_disabled(self):
        svc = AIService(self.db)
        svc.save_settings({"enabled": False})
        with self.assertRaises(AIProviderDisabledError):
            svc._provider_for()

    def test_block_cloud_provider_name(self):
        svc = AIService(self.db)
        with self.assertRaises(AIExternalConnectionBlockedError):
            svc.save_settings({"provider": "openai"})

    def test_block_external_url_on_save(self):
        svc = AIService(self.db)
        with self.assertRaises(AIExternalConnectionBlockedError):
            svc.save_settings({"base_url": "https://api.anthropic.com"})

    @patch("app.ai_local_engine.providers.ollama_provider.OllamaProvider.test_connection")
    def test_connection_success_mock(self, mock_conn):
        mock_conn.return_value = UnifiedAIResponse(
            success=True, text="ok", provider="ollama", response_time_ms=120
        )
        svc = AIService(self.db)
        svc.save_settings({"enabled": True, "base_url": "http://127.0.0.1:11434"})
        result = svc.test_connection()
        self.assertTrue(result.success)
        self.assertTrue(svc.get_settings().last_connection_ok)

    @patch("app.ai_local_engine.providers.ollama_provider.OllamaProvider.test_connection")
    def test_connection_failure_mock(self, mock_conn):
        mock_conn.return_value = UnifiedAIResponse(
            success=False,
            provider="ollama",
            error_code="connection_error",
            error_message="تعذر الاتصال بخدمة Ollama. تأكد من تشغيل Ollama ومن صحة عنوان الخادم المحلي.",
        )
        svc = AIService(self.db)
        result = svc.test_connection()
        self.assertFalse(result.success)
        self.assertFalse(svc.get_settings().last_connection_ok)

    def test_prompt_too_long(self):
        svc = AIService(self.db)
        svc.save_settings({"enabled": True, "model_name": "x"})
        with self.assertRaises(AIConfigurationError):
            svc.test_prompt("س" * 5000)

    @patch("app.ai_local_engine.services.ai_service.logger")
    @patch("app.ai_local_engine.providers.ollama_provider.OllamaProvider.generate_text")
    def test_no_prompt_in_logs(self, mock_gen, mock_logger):
        mock_gen.return_value = UnifiedAIResponse(
            success=True, text="جملة", provider="ollama", model="m", response_time_ms=500
        )
        svc = AIService(self.db)
        svc.save_settings({"enabled": True, "model_name": "m", "base_url": "http://127.0.0.1:11434"})
        secret = "اكتب جملة سرية لا تُسجَّل"
        svc.test_prompt(secret)
        for call in mock_logger.info.call_args_list:
            joined = " ".join(str(a) for a in call.args)
            self.assertNotIn(secret, joined)


class AiLocalOllamaProviderUnitTests(unittest.TestCase):
    @patch("app.ai_local_engine.providers.ollama_provider.httpx.Client")
    def test_model_not_found(self, mock_client_cls):
        from app.ai_local_engine.providers.ollama_provider import OllamaProvider

        client = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = client
        tags = MagicMock()
        tags.status_code = 200
        tags.content = b'{"models":[{"name":"other:latest"}]}'
        tags.json.return_value = {"models": [{"name": "other:latest"}]}
        client.request.return_value = tags
        p = OllamaProvider(base_url="http://127.0.0.1:11434", timeout=5, retry_count=0)
        result = p.generate_text(GenerateTextRequest(prompt="مرحبا", model_name="missing"))
        self.assertFalse(result.success)
        self.assertEqual(result.error_code, "model_not_found")

    @patch("app.ai_local_engine.providers.ollama_provider.httpx.Client")
    def test_empty_response(self, mock_client_cls):
        from app.ai_local_engine.providers.ollama_provider import OllamaProvider

        client = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = client

        def side_effect(method, url, json=None):
            resp = MagicMock()
            resp.status_code = 200
            if url.endswith("/api/tags"):
                resp.content = b'{"models":[{"name":"m:latest"}]}'
                resp.json.return_value = {"models": [{"name": "m:latest"}]}
            else:
                resp.content = b'{"message":{"content":"   "}}'
                resp.json.return_value = {"message": {"content": "   "}}
                resp.text = ""
            return resp

        client.request.side_effect = side_effect
        p = OllamaProvider(base_url="http://127.0.0.1:11434", timeout=5, retry_count=0)
        result = p.generate_text(GenerateTextRequest(prompt="x", model_name="m:latest"))
        self.assertFalse(result.success)
        self.assertEqual(result.error_code, "invalid_response")

    @patch("app.ai_local_engine.providers.ollama_provider.httpx.Client")
    def test_timeout(self, mock_client_cls):
        import httpx
        from app.ai_local_engine.providers.ollama_provider import OllamaProvider

        client = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = client
        client.request.side_effect = httpx.TimeoutException("timeout")
        p = OllamaProvider(base_url="http://127.0.0.1:11434", timeout=1, retry_count=0)
        result = p.test_connection()
        self.assertFalse(result.success)
        self.assertEqual(result.error_code, "timeout")

    @patch("app.ai_local_engine.providers.ollama_provider.httpx.Client")
    def test_generate_timing_excludes_model_lookup(self, mock_client_cls):
        """زمن الاستجابة = طلب /api/chat فقط وليس /api/tags."""
        import time
        from app.ai_local_engine.providers.ollama_provider import OllamaProvider

        client = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = client

        def side_effect(method, url, json=None):
            resp = MagicMock()
            resp.status_code = 200
            if url.endswith("/api/tags"):
                time.sleep(0.05)
                resp.content = b'{"models":[{"name":"m:latest"}]}'
                resp.json.return_value = {"models": [{"name": "m:latest"}]}
            else:
                time.sleep(0.02)
                resp.content = b'{"message":{"content":"yes"}}'
                resp.json.return_value = {"message": {"content": "yes"}}
                resp.text = "ok"
            return resp

        client.request.side_effect = side_effect
        p = OllamaProvider(base_url="http://127.0.0.1:11434", timeout=5, retry_count=0)
        result = p.generate_text(GenerateTextRequest(prompt="x", model_name="m:latest"))
        self.assertTrue(result.success)
        # يجب أن يكون قريباً من 20ms لا 70ms (tags+chat)
        self.assertLess(result.response_time_ms, 55)
        self.assertGreaterEqual(result.response_time_ms, 10)
        self.assertIsNotNone(result.timing_start)
        self.assertIsNotNone(result.timing_end)
        self.assertEqual(result.timing_debug()["raw_milliseconds"], result.response_time_ms)


class FormatDurationTests(unittest.TestCase):
    def test_format_rules(self):
        from app.ai_local_engine.timing import format_duration_ms

        self.assertEqual(format_duration_ms(184), "184 ms")
        self.assertEqual(format_duration_ms(1840), "1.84 ثانية")
        self.assertIn("دقيقة", format_duration_ms(125000))



if __name__ == "__main__":
    unittest.main()
