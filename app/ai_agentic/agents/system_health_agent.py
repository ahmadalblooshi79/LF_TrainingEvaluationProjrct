"""System Health Agent — اختبار البنية بدون تقارير مستخدم."""

from __future__ import annotations

import time
from typing import Any

from app.ai_agentic.agents.base_agent import BaseAgent
from app.ai_agentic.constants import SYSTEM_HEALTH_AGENT_KEY
from app.ai_agentic.exceptions import AgentOutputValidationError, OllamaConnectionError
from app.ai_agentic.json_util import extract_json_object
from app.ai_agentic.schemas import GatewayResult, StructuredAgentOutput

# عتبة تقريبية لاعتبار التحميل Cold (أول استدعاء بعد سكون النموذج)
_WARMUP_THRESHOLD_MS = 15000

_SYSTEM_PROMPT = "Return valid JSON only. No explanation."
_USER_PROMPT = 'Return:\n{"status":"ok","message":"Local model is available"}'


class SystemHealthAgent(BaseAgent):
    agent_key = SYSTEM_HEALTH_AGENT_KEY
    name = "System Health Agent"
    description = "Validates gateway, Ollama, model, structured output, and persistence."
    version = "1.0.0"
    max_retries = 0  # لا إعادة محاولة إلا عند فشل حقيقي يُضبط من Registry

    def build_prompt(self, context: dict[str, Any]) -> tuple[str, str]:
        pv = self.prompt_svc.get_active_for_agent(self.agent_key)
        if pv:
            self.prompt_version = pv.version
            system = (pv.system_prompt or "").strip() or _SYSTEM_PROMPT
            user = (pv.user_prompt_template or "").strip() or _USER_PROMPT
            # تفضيل البرومبت القصير إن كان المخزّن قديماً وطويلاً
            if len(system) > 120 or len(user) > 200:
                return _SYSTEM_PROMPT, _USER_PROMPT
            return system, user
        return _SYSTEM_PROMPT, _USER_PROMPT

    def execute(self, context: dict[str, Any], *, run_id: int | None = None) -> GatewayResult:
        params = dict(context.get("parameters") or {})
        params.setdefault("temperature", 0)
        params.setdefault("max_tokens", 48)
        params.setdefault("skip_model_precheck", True)
        params.setdefault("skip_model_ensure", True)
        params.setdefault("think", False)
        ctx = dict(context)
        ctx["parameters"] = params
        system_prompt, user_prompt = self.build_prompt(ctx)
        return self.gateway.send_request(
            agent_name=self.agent_key,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=self.model_name or None,
            parameters=params,
            run_id=run_id,
            timeout=float(self.timeout_seconds),
            prompt_version=self.prompt_version or None,
            max_retries_override=int(self.max_retries if self.max_retries is not None else 0),
        )

    def validate_output(self, gateway_result: GatewayResult) -> StructuredAgentOutput:
        t0 = time.perf_counter()
        if not gateway_result.success:
            raise AgentOutputValidationError(gateway_result.error or "فشل اختبار الصحة.")
        parsed = extract_json_object(gateway_result.content or "")
        if not parsed:
            raise AgentOutputValidationError("الاستجابة ليست JSON صالحاً.")
        status = str(parsed.get("status") or "").strip().lower()
        message = str(parsed.get("message") or "").strip()
        if status != "ok":
            raise AgentOutputValidationError(f"status غير متوقع: {status}")
        if not message:
            raise AgentOutputValidationError("حقل message مفقود.")
        validation_ms = int((time.perf_counter() - t0) * 1000)
        gateway_ms = int(gateway_result.duration_ms or 0)
        retry_count = int(gateway_result.retry_count or 0)
        warmup = gateway_ms >= _WARMUP_THRESHOLD_MS
        return StructuredAgentOutput(
            agent_key=self.agent_key,
            agent_version=self.version,
            status="success",
            confidence=1.0,
            data={
                "status": status,
                "message": message,
                "gateway_ok": True,
                "ollama_ok": True,
                "model": gateway_result.model,
                "parsed": parsed,
                "total_duration_ms": gateway_ms + validation_ms,
                "gateway_duration_ms": gateway_ms,
                "validation_duration_ms": validation_ms,
                "model_warmup_detected": warmup,
                "retry_count": retry_count,
            },
            warnings=(
                ["بطء محتمل بسبب تحميل النموذج (Cold start) — لا يُعد فشلاً."]
                if warmup
                else []
            ),
            errors=[],
            sources=[],
            metadata={
                "model": gateway_result.model,
                "prompt_version": self.prompt_version,
                "knowledge_version": self.knowledge_version,
                "duration_ms": gateway_ms,
                "total_duration_ms": gateway_ms + validation_ms,
                "gateway_duration_ms": gateway_ms,
                "validation_duration_ms": validation_ms,
                "model_warmup_detected": warmup,
                "retry_count": retry_count,
            },
        )

    def run(self, context: dict[str, Any] | None = None, *, run_id: int | None = None) -> StructuredAgentOutput:
        ctx = dict(context or {})
        try:
            settings = self.gateway.legacy_service.get_settings()
            if not settings.enabled:
                return self.handle_error(OllamaConnectionError("المحرك المحلي غير مفعّل."))
            model = (self.model_name or settings.model_name or "").strip()
            self.model_name = model
            # لا نفحص list_models هنا — يُترك لمحاولة التوليد المباشرة لتسريع الاختبار
        except OllamaConnectionError as exc:
            return self.handle_error(exc)
        except Exception as exc:  # noqa: BLE001
            return self.handle_error(exc)
        return super().run(ctx, run_id=run_id)
