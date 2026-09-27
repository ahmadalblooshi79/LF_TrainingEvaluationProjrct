"""جداول نقل بيانات التابلت — مطابقة يدوية وسجل عمليات (إضافة فقط)."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class TabletIdentityMapping(Base):
    """ربط هوية تاريخية من التابلت/التصدير بقائمة التمرين الحالية."""

    __tablename__ = "tablet_identity_mappings"
    __table_args__ = (
        Index("ix_tim_target_ex_eval", "target_exercise_id", "target_eval_item_id"),
        Index("ix_tim_source_eval", "source_exercise_id", "source_eval_item_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    source_exercise_id: Mapped[int | None] = mapped_column(nullable=True, index=True)
    source_exercise_name: Mapped[str] = mapped_column(String(256), default="")
    source_unit_id: Mapped[str] = mapped_column(String(128), default="", index=True)
    source_unit_name: Mapped[str] = mapped_column(String(256), default="")
    source_eval_item_id: Mapped[int | None] = mapped_column(nullable=True, index=True)
    source_eval_name: Mapped[str] = mapped_column(String(500), default="")
    source_eval_type: Mapped[str] = mapped_column(String(64), default="")
    source_device_id: Mapped[str] = mapped_column(String(128), default="")
    target_exercise_id: Mapped[int | None] = mapped_column(nullable=True, index=True)
    target_unit_id: Mapped[str] = mapped_column(String(128), default="")
    target_eval_item_id: Mapped[int] = mapped_column(index=True)
    created_by_id: Mapped[int | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)


class TabletTransferAudit(Base):
    __tablename__ = "tablet_transfer_audits"
    __table_args__ = (Index("ix_tta_created", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    operation_type: Mapped[str] = mapped_column(String(32), default="", index=True)
    device_id: Mapped[str] = mapped_column(String(128), default="", index=True)
    judge_id: Mapped[int | None] = mapped_column(nullable=True, index=True)
    unit_id: Mapped[str] = mapped_column(String(128), default="")
    exercise_id: Mapped[int | None] = mapped_column(nullable=True, index=True)
    source_eval_item_id: Mapped[int | None] = mapped_column(nullable=True)
    target_eval_item_id: Mapped[int | None] = mapped_column(nullable=True)
    match_method: Mapped[str] = mapped_column(String(64), default="")
    match_status: Mapped[str] = mapped_column(String(32), default="")
    mapping_id: Mapped[int | None] = mapped_column(nullable=True)
    operator_id: Mapped[int | None] = mapped_column(nullable=True)
    package_hash: Mapped[str] = mapped_column(String(64), default="", index=True)
    client_op_id: Mapped[str] = mapped_column(String(128), default="", index=True)
    details: Mapped[str] = mapped_column(Text(), default="")
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, index=True)


class TabletImportPackage(Base):
    """منع تكرار استيراد نفس الحزمة/الملف."""

    __tablename__ = "tablet_import_packages"
    __table_args__ = (
        UniqueConstraint("package_hash", name="uq_tablet_import_package_hash"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    package_hash: Mapped[str] = mapped_column(String(64), default="")
    package_name: Mapped[str] = mapped_column(String(256), default="")
    applied_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    operator_id: Mapped[int | None] = mapped_column(nullable=True)
    restored_count: Mapped[int] = mapped_column(default=0)
    details_json: Mapped[str] = mapped_column(Text(), default="")
