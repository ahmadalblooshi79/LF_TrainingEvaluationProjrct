"""نماذج مكتبة التقارير الذكية."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class AIReportSource(Base):
    __tablename__ = "ai_report_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    original_file_name: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    stored_file_name: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    stored_file_path: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    file_type: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    file_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False, index=True, default="")
    report_title: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    exercise_name: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    exercise_type: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    report_type: Mapped[str] = mapped_column(String(64), nullable=False, default="other")
    report_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    report_language: Mapped[str] = mapped_column(String(16), nullable=False, default="ar")
    classification_level: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    report_quality: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    is_approved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    allow_learning: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    processing_status: Mapped[str] = mapped_column(String(32), nullable=False, default="uploaded")
    processing_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    word_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    main_unit_name: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    main_unit_level: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    admin_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    needs_ocr: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    units_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    strengths_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    weaknesses_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sections_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    uploaded_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    processing_started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    processing_completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    sections = relationship("AIReportSection", back_populates="report", cascade="all, delete-orphan")
    tables = relationship("AIReportTable", back_populates="report", cascade="all, delete-orphan")
    units = relationship("AIReportUnit", back_populates="report", cascade="all, delete-orphan")
    findings = relationship("AIReportFinding", back_populates="report", cascade="all, delete-orphan")
    logs = relationship("AIReportProcessingLog", back_populates="report", cascade="all, delete-orphan")
    corrections = relationship("AIReportCorrection", back_populates="report", cascade="all, delete-orphan")


class AIReportSection(Base):
    __tablename__ = "ai_report_sections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("ai_report_sources.id", ondelete="CASCADE"), nullable=False, index=True)
    original_title: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    normalized_section_type: Mapped[str] = mapped_column(String(64), nullable=False, default="unknown")
    section_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    parent_section_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    original_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    cleaned_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    review_status: Mapped[str] = mapped_column(String(32), nullable=False, default="auto_detected")
    detection_source: Mapped[str] = mapped_column(String(32), nullable=False, default="rules")
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    report = relationship("AIReportSource", back_populates="sections")


class AIReportTable(Base):
    __tablename__ = "ai_report_tables"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("ai_report_sources.id", ondelete="CASCADE"), nullable=False, index=True)
    section_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    table_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    headers_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    rows_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    original_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.8)
    review_status: Mapped[str] = mapped_column(String(32), nullable=False, default="auto_detected")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    report = relationship("AIReportSource", back_populates="tables")


class AIReportUnit(Base):
    __tablename__ = "ai_report_units"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("ai_report_sources.id", ondelete="CASCADE"), nullable=False, index=True)
    original_unit_name: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    normalized_unit_name: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    unit_level: Mapped[str] = mapped_column(String(64), nullable=False, default="other")
    parent_unit_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    unit_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_brigade_level: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    detection_source: Mapped[str] = mapped_column(String(32), nullable=False, default="heading")
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.7)
    review_status: Mapped[str] = mapped_column(String(32), nullable=False, default="auto_detected")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    report = relationship("AIReportSource", back_populates="units")


class AIReportFinding(Base):
    __tablename__ = "ai_report_findings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("ai_report_sources.id", ondelete="CASCADE"), nullable=False, index=True)
    section_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    finding_type: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    original_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    cleaned_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    order_number: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    scope_type: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    objective_reference: Mapped[str | None] = mapped_column(String(256), nullable=True)
    evaluation_domain: Mapped[str | None] = mapped_column(String(128), nullable=True)
    severity: Mapped[str | None] = mapped_column(String(32), nullable=True)
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.7)
    review_status: Mapped[str] = mapped_column(String(32), nullable=False, default="auto_detected")
    detected_by: Mapped[str] = mapped_column(String(32), nullable=False, default="rules")
    allow_learning: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    report = relationship("AIReportSource", back_populates="findings")
    unit_links = relationship("AIReportFindingUnit", back_populates="finding", cascade="all, delete-orphan")


class AIReportFindingUnit(Base):
    __tablename__ = "ai_report_finding_units"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    finding_id: Mapped[int] = mapped_column(ForeignKey("ai_report_findings.id", ondelete="CASCADE"), nullable=False, index=True)
    report_unit_id: Mapped[int] = mapped_column(ForeignKey("ai_report_units.id", ondelete="CASCADE"), nullable=False, index=True)
    relation_type: Mapped[str] = mapped_column(String(32), nullable=False, default="primary")
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.7)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    finding = relationship("AIReportFinding", back_populates="unit_links")


class AIReportProcessingLog(Base):
    __tablename__ = "ai_report_processing_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("ai_report_sources.id", ondelete="CASCADE"), nullable=False, index=True)
    processing_step: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ok")
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    warning_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    report = relationship("AIReportSource", back_populates="logs")


class AIReportCorrection(Base):
    __tablename__ = "ai_report_corrections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("ai_report_sources.id", ondelete="CASCADE"), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    original_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    corrected_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    correction_type: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    corrected_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    corrected_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    approved_for_future_learning: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    report = relationship("AIReportSource", back_populates="corrections")
