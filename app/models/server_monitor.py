"""نماذج مراقبة الخادم والأجهزة والمزامنة."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ConnectedDevice(Base):
    """جهاز تابلت/عميل متصل بالنظام."""

    __tablename__ = "connected_devices"
    __table_args__ = (
        UniqueConstraint("device_id", name="uq_connected_devices_device_id"),
        Index("ix_connected_devices_last_activity", "last_activity_at"),
        Index("ix_connected_devices_status", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    device_id: Mapped[str] = mapped_column(String(128), default="", index=True)
    device_name: Mapped[str] = mapped_column(String(256), default="")
    device_ip: Mapped[str] = mapped_column(String(64), default="")
    user_id: Mapped[int | None] = mapped_column(nullable=True, index=True)
    military_number: Mapped[str] = mapped_column(String(64), default="", index=True)
    judge_name: Mapped[str] = mapped_column(String(256), default="")
    status: Mapped[str] = mapped_column(String(32), default="online")
    sync_status: Mapped[str] = mapped_column(String(32), default="idle")
    user_agent: Mapped[str] = mapped_column(String(512), default="")
    login_at: Mapped[datetime | None] = mapped_column(nullable=True)
    last_activity_at: Mapped[datetime | None] = mapped_column(nullable=True, index=True)
    last_sync_at: Mapped[datetime | None] = mapped_column(nullable=True)
    pending_sync_count: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, onupdate=datetime.utcnow)


class SyncOperationLog(Base):
    """سجل عمليات المزامنة (منع التكرار عبر client_operation_id)."""

    __tablename__ = "sync_operation_logs"
    __table_args__ = (
        UniqueConstraint("client_operation_id", name="uq_sync_op_client_id"),
        Index("ix_sync_op_device", "device_id"),
        Index("ix_sync_op_created", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    client_operation_id: Mapped[str] = mapped_column(String(128), default="")
    device_id: Mapped[str] = mapped_column(String(128), default="")
    user_id: Mapped[int | None] = mapped_column(nullable=True)
    operation_type: Mapped[str] = mapped_column(String(64), default="")
    target_url: Mapped[str] = mapped_column(String(700), default="")
    status: Mapped[str] = mapped_column(String(32), default="pending")
    error_message: Mapped[str] = mapped_column(Text(), default="")
    payload_hash: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, index=True)
    synced_at: Mapped[datetime | None] = mapped_column(nullable=True)


class ServerActivityLog(Base):
    __tablename__ = "server_activity_logs"
    __table_args__ = (Index("ix_server_activity_created", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    category: Mapped[str] = mapped_column(String(64), default="general", index=True)
    level: Mapped[str] = mapped_column(String(16), default="info")
    message: Mapped[str] = mapped_column(Text(), default="")
    user_id: Mapped[int | None] = mapped_column(nullable=True, index=True)
    device_id: Mapped[str] = mapped_column(String(128), default="")
    details_json: Mapped[str] = mapped_column(Text(), default="")
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, index=True)


class ServerErrorLog(Base):
    __tablename__ = "server_error_logs"
    __table_args__ = (Index("ix_server_error_created", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(128), default="")
    message: Mapped[str] = mapped_column(Text(), default="")
    traceback_text: Mapped[str] = mapped_column(Text(), default="")
    user_id: Mapped[int | None] = mapped_column(nullable=True)
    device_id: Mapped[str] = mapped_column(String(128), default="")
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, index=True)
