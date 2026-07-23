"""نموذج إعدادات الذكاء الاصطناعي المحلي في قاعدة البيانات."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AiSettings(Base):
    __tablename__ = "ai_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False, default="ollama")
    base_url: Mapped[str] = mapped_column(String(512), nullable=False, default="http://127.0.0.1:11434")
    model_name: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    temperature: Mapped[float] = mapped_column(Float, nullable=False, default=0.2)
    max_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=4096)
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=300)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    context_window: Mapped[int] = mapped_column(Integer, nullable=False, default=8192)
    response_language: Mapped[str] = mapped_column(String(16), nullable=False, default="ar")
    structured_output: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    allow_internal_network: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_connection_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    last_connection_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_response_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
