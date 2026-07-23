"""AI Gateway — الغلاف الوحيد لاستدعاء Ollama عبر AIService (Legacy)."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.ai_agentic import config as ag_config
from app.ai_agentic.exceptions import (
    ModelNotAvailableError,
    OllamaConnectionError,
)
from app.ai_agentic.schemas import GatewayResult
from app.ai_local_engine.exceptions import (
    AIConnectionError,
    AILocalEngineError,
    AIModelNotFoundError,
    AIRequestTimeoutError,
)
from app.ai_local_engine.schemas.request_schema import GenerateTextRequest
from app.ai_local_engine.services.ai_service import AIService

logger = logging.getLogger(__name__)


class AIGatewayService:
    """نقطة الاتصال الوحيدة للوكلاء مع المحرك المحلي — لا يستورد Ollama مباشرة."""

    def __init__(self, db: Session):
        self.db = db
        self._legacy = AIService(db)

    @property
    def legacy_service(self) -> AIService:
        return self._legacy

    def check_model_available(self, model: str | None = None) -> bool:
        settings = self._legacy.get_settings()
        target = (model or settings.model_name or "").strip()
        if not target:
            return False
        try:
            models = self._legacy.list_models()
        except AILocalEngineError:
            return False
        names = {(m.get("name") or "").strip() for m in models}
        if target in names:
            return True
        # تطابق مرن: qwen3:8b مقابل qwen3:8b-...
        return any(n == target or n.startswith(target + "-") or target.startswith(n) for n in names if n)

    def send_request(
        self,
        agent_name: str,
        system_prompt: str,
        user_prompt: str,
        model: str | None = None,
        parameters: dict[str, Any] | None = None,
        run_id: int | None = None,
        timeout: float | None = None,
        *,
        prompt_version: str | None = None,
        max_retries_override: int | None = None,
    ) -> GatewayResult:
        """واجهة موحدة للوكلاء. لا تكشف Exceptions الخام للمستخدم."""
        params = dict(parameters or {})
        settings = self._legacy.get_settings()
        model_name = (model or settings.model_name or ag_config.AI_DEFAULT_MODEL or "").strip()
        temp = params.get("temperature", settings.temperature)
        max_tokens = params.get("max_tokens", settings.max_tokens)
        to = float(timeout if timeout is not None else settings.timeout_seconds)
        skip_model_precheck = bool(params.get("skip_model_precheck"))
        skip_model_ensure = bool(params.get("skip_model_ensure"))
        think = params.get("think")

        log_meta = {
            "action": "gateway_send_request",
            "agent_name": agent_name,
            "run_id": run_id,
            "model": model_name,
            "prompt_version": prompt_version,
            "timeout": to,
        }
        if ag_config.AI_LOG_PROMPTS:
            log_meta["system_prompt_len"] = len(system_prompt or "")
            log_meta["user_prompt_len"] = len(user_prompt or "")
            log_meta["system_prompt"] = system_prompt
            log_meta["user_prompt"] = user_prompt
        else:
            log_meta["system_prompt_len"] = len(system_prompt or "")
            log_meta["user_prompt_len"] = len(user_prompt or "")
        logger.info("ai_gateway %s", {k: v for k, v in log_meta.items() if k not in ("system_prompt", "user_prompt") or ag_config.AI_LOG_PROMPTS})

        if not settings.enabled:
            return GatewayResult(
                success=False,
                model=model_name,
                error="الذكاء الاصطناعي المحلي غير مفعّل.",
                error_code="provider_disabled",
                agent_name=agent_name,
                run_id=run_id,
                prompt_version=prompt_version,
            )

        if not model_name:
            return GatewayResult(
                success=False,
                error="لم يُحدد نموذج محلي.",
                error_code="model_not_available",
                agent_name=agent_name,
                run_id=run_id,
                prompt_version=prompt_version,
            )

        if not skip_model_precheck:
            try:
                available = self.check_model_available(model_name)
                if not available:
                    logger.warning("ai_gateway model_maybe_unavailable model=%s", model_name)
            except Exception:  # noqa: BLE001
                logger.warning("ai_gateway model_check_failed", exc_info=True)

        ctx: dict[str, Any] = {
            "agent_name": agent_name,
            "run_id": run_id,
            "prompt_version": prompt_version,
        }
        if skip_model_ensure:
            ctx["skip_model_ensure"] = True
        if think is not None:
            ctx["think"] = bool(think)

        req = GenerateTextRequest(
            prompt=user_prompt or "",
            system_prompt=system_prompt or "",
            model_name=model_name,
            temperature=float(temp) if temp is not None else None,
            max_tokens=int(max_tokens) if max_tokens is not None else None,
            timeout=to,
            context=ctx,
        )

        # إعادة المحاولة على مستوى الـ Gateway (فوق retries المزود)
        # max_retries_override=0 → محاولة واحدة فقط
        if max_retries_override is not None:
            attempts = 1 + max(0, int(max_retries_override))
        else:
            attempts = 1 + max(0, int(settings.retry_count))
        last_error: str | None = None
        last_code: str | None = None
        retry_count_used = 0
        for attempt in range(1, attempts + 1):
            try:
                result = self._legacy.generate_text(req)
            except AIModelNotFoundError as exc:
                raise ModelNotAvailableError(exc.user_message) from exc
            except (AIConnectionError, AIRequestTimeoutError) as exc:
                last_error = exc.user_message
                last_code = exc.error_code
                logger.warning(
                    "ai_gateway attempt_failed attempt=%s code=%s",
                    attempt,
                    exc.error_code,
                )
                if attempt >= attempts:
                    raise OllamaConnectionError(exc.user_message) from exc
                retry_count_used += 1
                continue
            except AILocalEngineError as exc:
                return GatewayResult(
                    success=False,
                    model=model_name,
                    error=exc.user_message,
                    error_code=exc.error_code,
                    agent_name=agent_name,
                    run_id=run_id,
                    prompt_version=prompt_version,
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception("ai_gateway unexpected")
                return GatewayResult(
                    success=False,
                    model=model_name,
                    error="فشل طلب الذكاء الاصطناعي المحلي.",
                    error_code="gateway_error",
                    agent_name=agent_name,
                    run_id=run_id,
                    prompt_version=prompt_version,
                )

            raw: dict[str, Any] | None = None
            if ag_config.AI_SAVE_RAW_RESPONSES and result.raw_response is not None:
                if isinstance(result.raw_response, dict):
                    raw = result.raw_response
                else:
                    raw = {"value": str(result.raw_response)[:2000]}

            if result.success:
                return GatewayResult(
                    success=True,
                    content=result.text or "",
                    model=result.model or model_name,
                    duration_ms=int(result.response_time_ms or 0),
                    input_tokens=None,
                    output_tokens=None,
                    error=None,
                    raw_response=raw or {},
                    agent_name=agent_name,
                    run_id=run_id,
                    prompt_version=prompt_version,
                    retry_count=retry_count_used,
                )

            last_error = result.error_message or "فشل التوليد"
            last_code = result.error_code
            if attempt < attempts and result.error_code in ("connection_error", "timeout"):
                retry_count_used += 1
                continue
            return GatewayResult(
                success=False,
                content=result.text or "",
                model=result.model or model_name,
                duration_ms=int(result.response_time_ms or 0),
                error=last_error,
                error_code=last_code,
                raw_response=raw or {},
                agent_name=agent_name,
                run_id=run_id,
                prompt_version=prompt_version,
            )

        return GatewayResult(
            success=False,
            model=model_name,
            error=last_error or "فشل الاتصال بـ Ollama.",
            error_code=last_code or "ollama_connection_error",
            agent_name=agent_name,
            run_id=run_id,
            prompt_version=prompt_version,
        )
