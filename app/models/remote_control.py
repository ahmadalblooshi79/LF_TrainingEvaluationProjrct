"""نماذج جلسات التحكم المباشر (Live Remote Control) — التطبيق رقم 2."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class RemoteControlSession(Base):
    """جلسة تحكم مباشر نشطة أو منتهية."""

    __tablename__ = "remote_control_sessions"
    __table_args__ = (
        Index("ix_rc_sessions_active", "is_active"),
        Index("ix_rc_sessions_display", "display_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    username: Mapped[str] = mapped_column(String(64), default="")
    device_id: Mapped[str] = mapped_column(String(128), default="")
    device_label: Mapped[str] = mapped_column(String(200), default="")
    display_id: Mapped[str] = mapped_column(String(64), default="default", index=True)
    is_active: Mapped[bool] = mapped_column(default=True)
    is_locked: Mapped[bool] = mapped_column(default=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ended_by: Mapped[str] = mapped_column(String(64), default="")  # user | admin | lock
    last_path: Mapped[str] = mapped_column(String(500), default="/dashboard")
    last_state_json: Mapped[str] = mapped_column(Text(), default="{}")


class RemoteControlAuditLog(Base):
    """سجل أوامر التحكم المباشر."""

    __tablename__ = "remote_control_audit_logs"
    __table_args__ = (
        Index("ix_rc_audit_session", "session_id"),
        Index("ix_rc_audit_created", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[int | None] = mapped_column(
        ForeignKey("remote_control_sessions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    username: Mapped[str] = mapped_column(String(64), default="")
    device_id: Mapped[str] = mapped_column(String(128), default="")
    display_id: Mapped[str] = mapped_column(String(64), default="")
    action: Mapped[str] = mapped_column(String(64), default="")
    detail_json: Mapped[str] = mapped_column(Text(), default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
