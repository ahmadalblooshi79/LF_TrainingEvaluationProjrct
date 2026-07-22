"""فحص صحة محرك الذكاء الاصطناعي المحلي."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.ai_local_engine.exceptions import AILocalEngineError
from app.ai_local_engine.schemas.response_schema import HealthStatus
from app.ai_local_engine.services.ai_service import AIService


class HealthService:
    def __init__(self, db: Session):
        self.db = db
        self.ai = AIService(db)

    def check(self, *, probe_model: bool = True) -> HealthStatus:
        settings = self.ai.get_settings()
        status = HealthStatus(
            ai_enabled=settings.enabled,
            provider=settings.provider,
            model_name=settings.model_name,
            last_checked_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
            last_error=settings.last_error,
        )
        if not settings.enabled:
            status.last_error = "الذكاء الاصطناعي المحلي غير مفعّل."
            return status
        try:
            provider = self.ai._provider_for(settings)
            raw = provider.health_check(settings.model_name if probe_model else None)
            status.server_reachable = bool(raw.get("server_reachable"))
            status.model_available = bool(raw.get("model_available"))
            status.model_responding = bool(raw.get("model_responding"))
            status.response_time = raw.get("response_time")
            if raw.get("response_time_ms") is not None:
                status.response_time_ms = int(raw["response_time_ms"])
            elif status.response_time is not None:
                status.response_time_ms = int(round(float(status.response_time) * 1000))
            if raw.get("last_error"):
                status.last_error = str(raw["last_error"])
        except AILocalEngineError as exc:
            status.server_reachable = False
            status.last_error = exc.user_message
        except Exception:
            status.server_reachable = False
            status.last_error = "تعذر إكمال فحص الصحة."
        return status
