"""مزود Ollama المحلي — API على 127.0.0.1:11434 فقط."""

from __future__ import annotations

import json
import time
from typing import Any

import httpx

from app.ai_local_engine.exceptions import (
    AIConnectionError,
    AIInvalidResponseError,
    AIModelNotFoundError,
    AIRequestTimeoutError,
)
from app.ai_local_engine.providers.base_provider import BaseAIProvider
from app.ai_local_engine.schemas.request_schema import GenerateTextRequest
from app.ai_local_engine.schemas.response_schema import UnifiedAIResponse
from app.ai_local_engine.timing import HttpRequestTimer, RequestTiming


class OllamaProvider(BaseAIProvider):
    provider_name = "ollama"

    def _client(self, timeout: float | None = None) -> httpx.Client:
        return httpx.Client(timeout=timeout if timeout is not None else self.timeout)

    def _url(self, path: str) -> str:
        return f"{self.base_url.rstrip('/')}{path}"

    def _request_with_retry(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> tuple[httpx.Response, RequestTiming]:
        """
        يعيد الاستجابة وتوقيت الطلب الناجح (أو آخر محاولة) فقط —
        بدون احتساب نوم إعادة المحاولة أو منطق التحقق خارج HTTP.
        """
        attempts = self.retry_count + 1
        last_exc: Exception | None = None
        last_timing: RequestTiming | None = None
        for attempt in range(attempts):
            timer = HttpRequestTimer()
            started = False
            try:
                with self._client(timeout=timeout) as client:
                    timer.start()
                    started = True
                    resp = client.request(method, self._url(path), json=json_body)
                    # ضمان اكتمال قراءة الجسم (آخر بايت) داخل نافذة القياس
                    _ = resp.content
                    timing = timer.stop()
                    last_timing = timing
                    return resp, timing
            except httpx.TimeoutException as exc:
                if started:
                    last_timing = timer.stop()
                last_exc = exc
                if attempt + 1 >= attempts:
                    raise AIRequestTimeoutError() from exc
            except httpx.HTTPError as exc:
                if started:
                    last_timing = timer.stop()
                last_exc = exc
                if attempt + 1 >= attempts:
                    raise AIConnectionError() from exc
            # نوم إعادة المحاولة خارج قياس زمن الاستجابة
            time.sleep(min(0.35 * (attempt + 1), 1.5))
        raise AIConnectionError() from last_exc

    @staticmethod
    def _empty_timing() -> RequestTiming:
        t = HttpRequestTimer()
        t.start()
        return t.stop()

    def _fail(
        self,
        *,
        error_code: str,
        error_message: str,
        model: str = "",
        timing: RequestTiming | None = None,
    ) -> UnifiedAIResponse:
        timing = timing or self._empty_timing()
        return UnifiedAIResponse(
            success=False,
            provider=self.provider_name,
            model=model,
            response_time_ms=timing.raw_milliseconds,
            timing_start=timing.start_time,
            timing_end=timing.end_time,
            error_code=error_code,
            error_message=error_message,
            metadata={"timing": timing.to_debug_dict()},
        )

    def test_connection(self) -> UnifiedAIResponse:
        timing: RequestTiming | None = None
        try:
            resp, timing = self._request_with_retry(
                "GET", "/api/tags", timeout=min(30.0, self.timeout)
            )
            if resp.status_code >= 400:
                return self._fail(
                    error_code="connection_error",
                    error_message=AIConnectionError.user_message,
                    timing=timing,
                )
            data = resp.json()
            models = data.get("models") or []
            return UnifiedAIResponse(
                success=True,
                text=f"الاتصال ناجح — {len(models)} نموذجاً محلياً.",
                provider=self.provider_name,
                response_time_ms=timing.raw_milliseconds,
                timing_start=timing.start_time,
                timing_end=timing.end_time,
                metadata={
                    "model_count": len(models),
                    "timing": timing.to_debug_dict(),
                },
                raw_response=data,
            )
        except (AIConnectionError, AIRequestTimeoutError) as exc:
            return self._fail(
                error_code=exc.error_code,
                error_message=exc.user_message,
                timing=timing,
            )
        except Exception:
            return self._fail(
                error_code="connection_error",
                error_message=AIConnectionError.user_message,
                timing=timing,
            )

    def list_models(self) -> list[dict[str, Any]]:
        resp, _timing = self._request_with_retry(
            "GET", "/api/tags", timeout=min(30.0, self.timeout)
        )
        if resp.status_code >= 400:
            raise AIConnectionError()
        data = resp.json()
        out: list[dict[str, Any]] = []
        for m in data.get("models") or []:
            name = (m.get("name") or m.get("model") or "").strip()
            if not name:
                continue
            out.append(
                {
                    "name": name,
                    "size": m.get("size"),
                    "modified_at": m.get("modified_at"),
                    "digest": m.get("digest"),
                    "details": m.get("details") or {},
                }
            )
        return out

    def get_model_info(self, model_name: str) -> dict[str, Any]:
        name = (model_name or "").strip()
        if not name:
            raise AIModelNotFoundError()
        models = self.list_models()
        for m in models:
            if m["name"] == name or m["name"].startswith(name + ":"):
                return m
        raise AIModelNotFoundError()

    def _ensure_model(self, model_name: str) -> str:
        name = (model_name or "").strip()
        if not name:
            raise AIModelNotFoundError("لم يُحدد اسم النموذج.")
        models = self.list_models()
        names = {m["name"] for m in models}
        if name in names:
            return name
        for n in names:
            if n == name or n.startswith(name + ":") or name.startswith(n.split(":")[0]):
                if n.split(":")[0] == name.split(":")[0]:
                    return n
        raise AIModelNotFoundError()

    def generate_text(self, request: GenerateTextRequest) -> UnifiedAIResponse:
        model = ""
        timing: RequestTiming | None = None
        try:
            ctx = dict(request.context or {})
            # التحقق من النموذج خارج نافذة قياس زمن التوليد
            # يمكن تخطي list_models عند معرفة الاسم مسبقاً (مثل اختبار الصحة السريع)
            if ctx.get("skip_model_ensure"):
                model = (request.model_name or "").strip()
                if not model:
                    raise AIModelNotFoundError("لم يُحدد اسم النموذج.")
            else:
                model = self._ensure_model(request.model_name or "")
            messages: list[dict[str, str]] = []
            if (request.system_prompt or "").strip():
                messages.append({"role": "system", "content": request.system_prompt.strip()})
            messages.append({"role": "user", "content": (request.prompt or "").strip()})
            if not messages[-1]["content"]:
                raise AIInvalidResponseError("نص الطلب فارغ.")

            options: dict[str, Any] = {}
            temp = request.temperature
            if temp is not None:
                options["temperature"] = float(temp)
            if request.max_tokens is not None:
                options["num_predict"] = int(request.max_tokens)

            body: dict[str, Any] = {
                "model": model,
                "messages": messages,
                "stream": False,
            }
            # Qwen3 / نماذج التفكير: تعطيل التفكير المطول عند الطلب
            if "think" in ctx:
                body["think"] = bool(ctx.get("think"))
            if options:
                body["options"] = options

            timeout = request.timeout if request.timeout is not None else self.timeout
            resp, timing = self._request_with_retry(
                "POST", "/api/chat", json_body=body, timeout=timeout
            )
            if resp.status_code >= 400:
                text_err = (resp.text or "").lower()
                if resp.status_code == 404 or "not found" in text_err:
                    raise AIModelNotFoundError()
                raise AIConnectionError()
            data = resp.json()
            msg = (data.get("message") or {}) if isinstance(data, dict) else {}
            text = (msg.get("content") or "").strip()
            if not text:
                raise AIInvalidResponseError()
            return UnifiedAIResponse(
                success=True,
                text=text,
                provider=self.provider_name,
                model=model,
                response_time_ms=timing.raw_milliseconds,
                timing_start=timing.start_time,
                timing_end=timing.end_time,
                metadata={
                    "eval_count": data.get("eval_count"),
                    "done": data.get("done"),
                    "timing": timing.to_debug_dict(),
                },
                raw_response=data,
            )
        except (
            AIModelNotFoundError,
            AIInvalidResponseError,
            AIConnectionError,
            AIRequestTimeoutError,
        ) as exc:
            return self._fail(
                error_code=exc.error_code,
                error_message=exc.user_message,
                model=model,
                timing=timing,
            )
        except Exception:
            return self._fail(
                error_code="connection_error",
                error_message=AIConnectionError.user_message,
                model=model,
                timing=timing,
            )

    def generate_structured_output(self, request: GenerateTextRequest) -> UnifiedAIResponse:
        """محاولة إخراج JSON عبر format=json في Ollama عند الإمكان."""
        model = ""
        timing: RequestTiming | None = None
        try:
            model = self._ensure_model(request.model_name or "")
            system = (request.system_prompt or "").strip()
            if "json" not in system.lower():
                system = (
                    (system + "\n") if system else ""
                ) + "أجب بصيغة JSON صالحة فقط دون نص إضافي."
            messages = [
                {"role": "system", "content": system},
                {"role": "user", "content": (request.prompt or "").strip()},
            ]
            options: dict[str, Any] = {}
            if request.temperature is not None:
                options["temperature"] = float(request.temperature)
            if request.max_tokens is not None:
                options["num_predict"] = int(request.max_tokens)
            body: dict[str, Any] = {
                "model": model,
                "messages": messages,
                "stream": False,
                "format": "json",
            }
            if options:
                body["options"] = options
            timeout = request.timeout if request.timeout is not None else self.timeout
            resp, timing = self._request_with_retry(
                "POST", "/api/chat", json_body=body, timeout=timeout
            )
            if resp.status_code >= 400:
                return self.generate_text(request)
            data = resp.json()
            msg = (data.get("message") or {}) if isinstance(data, dict) else {}
            text = (msg.get("content") or "").strip()
            if not text:
                raise AIInvalidResponseError()
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = None
            return UnifiedAIResponse(
                success=True,
                text=text,
                provider=self.provider_name,
                model=model,
                response_time_ms=timing.raw_milliseconds,
                timing_start=timing.start_time,
                timing_end=timing.end_time,
                metadata={
                    "structured": True,
                    "parsed_ok": parsed is not None,
                    "timing": timing.to_debug_dict(),
                },
                raw_response=data,
            )
        except (
            AIModelNotFoundError,
            AIInvalidResponseError,
            AIConnectionError,
            AIRequestTimeoutError,
        ) as exc:
            return self._fail(
                error_code=exc.error_code,
                error_message=exc.user_message,
                model=model,
                timing=timing,
            )
        except Exception:
            return self.generate_text(request)

    def health_check(self, model_name: str | None = None) -> dict[str, Any]:
        conn = self.test_connection()
        result: dict[str, Any] = {
            "server_reachable": conn.success,
            "model_available": False,
            "model_responding": False,
            "response_time": conn.response_time,
            "response_time_ms": conn.response_time_ms,
            "last_error": None if conn.success else conn.error_message,
            "provider": self.provider_name,
            "timing": conn.timing_debug(),
        }
        if not conn.success:
            return result
        name = (model_name or "").strip()
        if not name:
            return result
        try:
            self.get_model_info(name)
            result["model_available"] = True
        except AIModelNotFoundError as exc:
            result["last_error"] = exc.user_message
            return result
        probe = self.generate_text(
            GenerateTextRequest(
                prompt="قل: نعم",
                system_prompt="أجب بكلمة واحدة فقط.",
                model_name=name,
                temperature=0.0,
                max_tokens=8,
                timeout=min(60.0, self.timeout),
            )
        )
        result["model_responding"] = probe.success
        result["response_time"] = probe.response_time
        result["response_time_ms"] = probe.response_time_ms
        result["timing"] = probe.timing_debug()
        if not probe.success:
            result["last_error"] = probe.error_message
        return result
