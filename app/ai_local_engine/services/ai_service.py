"""خدمة الذكاء الاصطناعي المحلية المركزية."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.ai_local_engine import config as ai_config
from app.ai_local_engine.exceptions import (
    AIConfigurationError,
    AIExternalConnectionBlockedError,
    AILocalEngineError,
    AIProviderDisabledError,
    AIProviderNotConfiguredError,
)
from app.ai_local_engine.models import AiSettings
from app.ai_local_engine.providers import get_provider
from app.ai_local_engine.schemas.request_schema import GenerateTextRequest
from app.ai_local_engine.schemas.response_schema import AISettingsDTO, UnifiedAIResponse
from app.ai_local_engine.security import assert_no_cloud_provider, validate_ai_base_url

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _dto_from_row(row: AiSettings) -> AISettingsDTO:
    return AISettingsDTO(
        enabled=bool(row.enabled),
        provider=(row.provider or "ollama").strip().lower(),
        base_url=(row.base_url or "").strip(),
        model_name=(row.model_name or "").strip(),
        temperature=float(row.temperature if row.temperature is not None else 0.2),
        max_tokens=int(row.max_tokens or 4096),
        timeout_seconds=int(row.timeout_seconds or 300),
        retry_count=int(row.retry_count if row.retry_count is not None else 2),
        context_window=int(row.context_window or 8192),
        response_language=(row.response_language or "ar").strip() or "ar",
        structured_output=bool(row.structured_output),
        allow_internal_network=bool(row.allow_internal_network),
        allow_internet=False,
        telemetry=False,
        log_prompts=bool(ai_config.AI_LOG_PROMPTS),
        log_responses=bool(ai_config.AI_LOG_RESPONSES),
        last_connection_ok=row.last_connection_ok,
        last_connection_at=row.last_connection_at.isoformat(sep=" ", timespec="seconds")
        if row.last_connection_at
        else None,
        last_response_ms=row.last_response_ms,
        last_error=row.last_error,
    )


def ensure_default_settings(db: Session) -> AiSettings:
    row = db.query(AiSettings).order_by(AiSettings.id.asc()).first()
    if row:
        return row
    row = AiSettings(
        enabled=bool(ai_config.AI_ENABLED),
        provider=ai_config.AI_PROVIDER if ai_config.AI_PROVIDER in ai_config.ALLOWED_PROVIDERS else "ollama",
        base_url=ai_config.AI_BASE_URL or "http://127.0.0.1:11434",
        model_name=ai_config.AI_MODEL_NAME or "",
        temperature=float(ai_config.AI_TEMPERATURE),
        max_tokens=int(ai_config.AI_MAX_TOKENS),
        timeout_seconds=int(ai_config.AI_TIMEOUT_SECONDS),
        retry_count=int(ai_config.AI_RETRY_COUNT),
        context_window=int(ai_config.AI_CONTEXT_WINDOW),
        response_language=ai_config.AI_RESPONSE_LANGUAGE or "ar",
        structured_output=bool(ai_config.AI_STRUCTURED_OUTPUT),
        allow_internal_network=bool(ai_config.AI_ALLOW_INTERNAL_NETWORK),
        created_at=_utcnow(),
        updated_at=_utcnow(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


class AIService:
    """نقطة الدخول الوحيدة للواجهة ومسارات API."""

    def __init__(self, db: Session):
        self.db = db

    def get_settings(self) -> AISettingsDTO:
        row = ensure_default_settings(self.db)
        return _dto_from_row(row)

    def _row(self) -> AiSettings:
        return ensure_default_settings(self.db)

    def save_settings(self, payload: dict[str, Any], *, user_id: int | None = None) -> AISettingsDTO:
        row = self._row()
        if "enabled" in payload:
            row.enabled = bool(payload["enabled"])
        if "provider" in payload:
            provider = str(payload["provider"] or "").strip().lower()
            assert_no_cloud_provider(provider)
            if provider not in ai_config.ALLOWED_PROVIDERS:
                raise AIConfigurationError("المزود المحدد غير مدعوم.")
            row.provider = provider
        if "base_url" in payload:
            allow_net = bool(payload.get("allow_internal_network", row.allow_internal_network))
            row.base_url = validate_ai_base_url(
                str(payload["base_url"] or ""),
                allow_internal_network=allow_net,
            )
        if "model_name" in payload:
            row.model_name = str(payload["model_name"] or "").strip()[:256]
        if "temperature" in payload:
            try:
                row.temperature = max(0.0, min(2.0, float(payload["temperature"])))
            except (TypeError, ValueError) as exc:
                raise AIConfigurationError("قيمة Temperature غير صالحة.") from exc
        if "max_tokens" in payload:
            try:
                row.max_tokens = max(1, int(payload["max_tokens"]))
            except (TypeError, ValueError) as exc:
                raise AIConfigurationError("قيمة Max Tokens غير صالحة.") from exc
        if "timeout_seconds" in payload:
            try:
                row.timeout_seconds = max(5, int(payload["timeout_seconds"]))
            except (TypeError, ValueError) as exc:
                raise AIConfigurationError("قيمة المهلة غير صالحة.") from exc
        if "retry_count" in payload:
            try:
                row.retry_count = max(0, min(5, int(payload["retry_count"])))
            except (TypeError, ValueError) as exc:
                raise AIConfigurationError("قيمة إعادة المحاولة غير صالحة.") from exc
        if "context_window" in payload:
            try:
                row.context_window = max(512, int(payload["context_window"]))
            except (TypeError, ValueError) as exc:
                raise AIConfigurationError("قيمة نافذة السياق غير صالحة.") from exc
        if "response_language" in payload:
            row.response_language = str(payload["response_language"] or "ar").strip()[:16] or "ar"
        if "structured_output" in payload:
            row.structured_output = bool(payload["structured_output"])
        if "allow_internal_network" in payload:
            row.allow_internal_network = bool(payload["allow_internal_network"])
            # إعادة التحقق من العنوان الحالي
            row.base_url = validate_ai_base_url(
                row.base_url,
                allow_internal_network=row.allow_internal_network,
            )

        # فرض سياسات الأمان
        if ai_config.AI_ALLOW_INTERNET:
            pass  # لا نفعّل الإنترنت حتى لو وُجدت القيمة في env للمرحلة 1
        row.updated_at = _utcnow()
        row.updated_by = user_id
        self.db.commit()
        self.db.refresh(row)
        self._safe_log("settings_saved", provider=row.provider, model=row.model_name, ok=True)
        return _dto_from_row(row)

    def _provider_for(self, settings: AISettingsDTO | None = None):
        s = settings or self.get_settings()
        if not s.enabled:
            raise AIProviderDisabledError()
        assert_no_cloud_provider(s.provider)
        if s.provider not in ai_config.ALLOWED_PROVIDERS:
            raise AIProviderNotConfiguredError()
        if s.allow_internet or ai_config.AI_ALLOW_INTERNET:
            # المرحلة 1: الإنترنت ممنوع دائماً من المحرك المحلي
            raise AIExternalConnectionBlockedError(
                "الاتصال بالإنترنت غير مسموح لمحرك الذكاء الاصطناعي المحلي."
            )
        base = validate_ai_base_url(s.base_url, allow_internal_network=s.allow_internal_network)
        return get_provider(
            s.provider,
            base_url=base,
            timeout=float(s.timeout_seconds),
            retry_count=int(s.retry_count),
        )

    def _record_connection_result(self, result: UnifiedAIResponse) -> None:
        row = self._row()
        row.last_connection_ok = bool(result.success)
        row.last_connection_at = _utcnow()
        # حفظ الزمن الخام بالمللي ثانية كما قيس من طلب Ollama فقط
        row.last_response_ms = int(result.response_time_ms or 0)
        row.last_error = None if result.success else (result.error_message or result.error_code)
        row.updated_at = _utcnow()
        self.db.commit()

    def test_connection(self) -> UnifiedAIResponse:
        settings = self.get_settings()
        try:
            provider = self._provider_for(settings)
            result = provider.test_connection()
        except AILocalEngineError as exc:
            result = UnifiedAIResponse(
                success=False,
                provider=settings.provider,
                model=settings.model_name,
                error_code=exc.error_code,
                error_message=exc.user_message,
            )
        self._record_connection_result(result)
        self._safe_log(
            "test_connection",
            provider=settings.provider,
            model=settings.model_name,
            ok=result.success,
            error_code=result.error_code,
            ms=int(result.response_time_ms or 0),
        )
        return result

    def list_models(self) -> list[dict[str, Any]]:
        settings = self.get_settings()
        provider = self._provider_for(settings)
        models = provider.list_models()
        self._safe_log(
            "list_models",
            provider=settings.provider,
            model=settings.model_name,
            ok=True,
            count=len(models),
        )
        return models

    def test_prompt(self, prompt: str, *, system_prompt: str = "") -> UnifiedAIResponse:
        settings = self.get_settings()
        text = (prompt or "").strip()
        if not text:
            raise AIConfigurationError("نص الاختبار فارغ.")
        if len(text) > ai_config.MAX_TEST_PROMPT_CHARS:
            raise AIConfigurationError(
                f"تجاوز نص الاختبار الحد الأقصى ({ai_config.MAX_TEST_PROMPT_CHARS} حرفاً)."
            )
        provider = self._provider_for(settings)
        if not (settings.model_name or "").strip():
            raise AIConfigurationError("اختر نموذجاً محلياً أولاً من قائمة النماذج.")
        req = GenerateTextRequest(
            prompt=text,
            system_prompt=system_prompt
            or f"أجب باللغة {settings.response_language}. كن موجزاً ورسمياً.",
            model_name=settings.model_name,
            temperature=settings.temperature,
            max_tokens=min(settings.max_tokens, 1024),
            timeout=float(settings.timeout_seconds),
        )
        if settings.structured_output:
            # للاختبار النصي العادي نستخدم generate_text
            result = provider.generate_text(req)
        else:
            result = provider.generate_text(req)
        self._record_connection_result(result)
        self._safe_log(
            "test_prompt",
            provider=settings.provider,
            model=settings.model_name,
            ok=result.success,
            error_code=result.error_code,
            ms=int(result.response_time_ms or 0),
            prompt_len=len(text),
        )
        return result

    def generate_text(self, request: GenerateTextRequest) -> UnifiedAIResponse:
        settings = self.get_settings()
        provider = self._provider_for(settings)
        model = (request.model_name or settings.model_name or "").strip()
        req = GenerateTextRequest(
            prompt=request.prompt,
            system_prompt=request.system_prompt,
            model_name=model,
            temperature=request.temperature if request.temperature is not None else settings.temperature,
            max_tokens=request.max_tokens if request.max_tokens is not None else settings.max_tokens,
            timeout=request.timeout if request.timeout is not None else float(settings.timeout_seconds),
            context=request.context,
        )
        if settings.structured_output and request.context and request.context.get("structured"):
            result = provider.generate_structured_output(req)
        else:
            result = provider.generate_text(req)
        self._safe_log(
            "generate_text",
            provider=settings.provider,
            model=model,
            ok=result.success,
            error_code=result.error_code,
            ms=int(result.response_time_ms or 0),
        )
        return result

    @staticmethod
    def _safe_log(action: str, *, provider: str, model: str, ok: bool, **extra: Any) -> None:
        # لا يسجّل محتوى Prompt أو Response
        payload = {
            "action": action,
            "provider": provider,
            "model": model,
            "ok": ok,
            **{k: v for k, v in extra.items() if k not in ("prompt", "response", "text")},
        }
        logger.info("ai_local_engine %s", payload)
