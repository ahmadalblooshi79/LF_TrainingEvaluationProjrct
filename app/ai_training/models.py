"""نماذج ORM لمركز التدريب."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AiTrainingDocument(Base):
    __tablename__ = "ai_training_documents"
    __table_args__ = (
        UniqueConstraint("document_uuid", name="uq_ai_training_document_uuid"),
        Index("ix_ai_training_docs_group", "document_group_uuid"),
        Index("ix_ai_training_docs_sha", "sha256_hash"),
        Index("ix_ai_training_docs_type", "document_type"),
        Index("ix_ai_training_docs_status", "status"),
        Index("ix_ai_training_docs_ext_status", "extraction_status"),
        Index("ix_ai_training_docs_rev_status", "review_status"),
        Index("ix_ai_training_docs_apr_status", "approval_status"),
        Index("ix_ai_training_docs_uploader", "uploaded_by_user_id"),
        Index("ix_ai_training_docs_created", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_uuid: Mapped[str] = mapped_column(String(64), nullable=False)
    document_group_uuid: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    original_filename: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    stored_filename: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    storage_path: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    document_type: Mapped[str] = mapped_column(String(64), nullable=False, default="other")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_organization: Mapped[str | None] = mapped_column(String(256), nullable=True)
    document_date: Mapped[str | None] = mapped_column(String(32), nullable=True)
    language: Mapped[str] = mapped_column(String(16), nullable=False, default="ar")
    version_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    version_label: Mapped[str | None] = mapped_column(String(128), nullable=True)
    is_latest_version: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    replaced_by_document_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    file_extension: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sha256_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    paragraph_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    table_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(64), nullable=False, default="UPLOADED")
    extraction_status: Mapped[str] = mapped_column(String(64), nullable=False, default="NOT_STARTED")
    review_status: Mapped[str] = mapped_column(String(64), nullable=False, default="NOT_REVIEWED")
    approval_status: Mapped[str] = mapped_column(String(64), nullable=False, default="NOT_APPROVED")
    uploaded_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reviewed_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    approved_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latest_workflow_run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    extracted_text_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    extraction_metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Phase B2.1 — Structure Analysis (independent of extraction approval)
    structure_status: Mapped[str] = mapped_column(String(64), nullable=False, default="NOT_STARTED")
    latest_structure_run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    structure_approved_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    structure_approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    structure_locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class AiTrainingDocumentPage(Base):
    __tablename__ = "ai_training_document_pages"
    __table_args__ = (Index("ix_ai_training_pages_doc_page", "document_id", "page_number"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("ai_training_documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_label: Mapped[str | None] = mapped_column(String(64), nullable=True)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    cleaned_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    extraction_method: Mapped[str | None] = mapped_column(String(64), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    character_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class AiTrainingDocumentBlock(Base):
    __tablename__ = "ai_training_document_blocks"
    __table_args__ = (Index("ix_ai_training_blocks_doc_idx", "document_id", "block_index"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("ai_training_documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    page_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    block_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    block_type: Mapped[str] = mapped_column(String(32), nullable=False, default="paragraph")
    text_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    original_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    style_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    heading_level: Mapped[int | None] = mapped_column(Integer, nullable=True)
    list_level: Mapped[int | None] = mapped_column(Integer, nullable=True)
    numbering_text: Mapped[str | None] = mapped_column(String(64), nullable=True)
    bounding_box_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    table_data_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_reference: Mapped[str | None] = mapped_column(String(256), nullable=True)
    extraction_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_removed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class AiTrainingDocumentReview(Base):
    __tablename__ = "ai_training_document_reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("ai_training_documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    reviewer_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    review_status: Mapped[str] = mapped_column(String(64), nullable=False, default="IN_REVIEW")
    review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    total_issues: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    corrected_blocks_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class AiTrainingDocumentCorrection(Base):
    __tablename__ = "ai_training_document_corrections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("ai_training_documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    block_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    review_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    correction_type: Mapped[str] = mapped_column(String(64), nullable=False, default="OTHER")
    original_value_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    corrected_value_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    corrected_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class AiTrainingDocumentEvent(Base):
    __tablename__ = "ai_training_document_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("ai_training_documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    workflow_run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    agent_run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(32), nullable=False, default="info")
    message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    details_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


# —— Phase B2.1 Military Structure Analysis (independent layer) ——


class AiTrainingStructureRun(Base):
    __tablename__ = "ai_training_structure_runs"
    __table_args__ = (
        Index("ix_ai_struct_runs_doc", "document_id"),
        Index("ix_ai_struct_runs_status", "status"),
        Index("ix_ai_struct_runs_created", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("ai_training_documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    workflow_run_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(64), nullable=False, default="CREATED")
    structure_version: Mapped[str] = mapped_column(String(32), nullable=False, default="1.0.0")
    model_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    knowledge_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    total_blocks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    analyzed_blocks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_structures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    low_confidence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    conflict_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    approved_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    error_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class AiTrainingDocumentStructure(Base):
    __tablename__ = "ai_training_document_structures"
    __table_args__ = (
        Index("ix_ai_structs_run", "structure_run_id"),
        Index("ix_ai_structs_doc", "document_id"),
        Index("ix_ai_structs_block", "block_id"),
        Index("ix_ai_structs_parent", "parent_structure_id"),
        Index("ix_ai_structs_role", "detected_role"),
        Index("ix_ai_structs_num_level", "numbering_level"),
        Index("ix_ai_structs_conf", "confidence"),
        Index("ix_ai_structs_reviewer", "reviewer_status"),
        Index("ix_ai_structs_created", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    structure_run_id: Mapped[int] = mapped_column(
        ForeignKey("ai_training_structure_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_id: Mapped[int] = mapped_column(
        ForeignKey("ai_training_documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    block_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    parent_structure_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    detected_role: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    numbering_text: Mapped[str | None] = mapped_column(String(64), nullable=True)
    numbering_style: Mapped[str | None] = mapped_column(String(64), nullable=True)
    numbering_level: Mapped[int | None] = mapped_column(Integer, nullable=True)
    indentation_level: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sequence_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    title_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_heading: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_content: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    evidence_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    warnings_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    detection_source: Mapped[str] = mapped_column(String(32), nullable=False, default="rule")
    rule_result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    llm_result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewer_status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING")
    reviewer_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class AiTrainingStructureCorrection(Base):
    __tablename__ = "ai_training_structure_corrections"
    __table_args__ = (
        Index("ix_ai_struct_corr_run", "structure_run_id"),
        Index("ix_ai_struct_corr_doc", "document_id"),
        Index("ix_ai_struct_corr_struct", "structure_id"),
        Index("ix_ai_struct_corr_block", "block_id"),
        Index("ix_ai_struct_corr_created", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    structure_run_id: Mapped[int] = mapped_column(
        ForeignKey("ai_training_structure_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    structure_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("ai_training_documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    block_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    correction_type: Mapped[str] = mapped_column(String(64), nullable=False, default="STRUCTURE_CORRECTION")
    original_value_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    corrected_value_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    corrected_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class AiTrainingDocumentOutline(Base):
    __tablename__ = "ai_training_document_outlines"
    __table_args__ = (
        Index("ix_ai_outline_run", "structure_run_id"),
        Index("ix_ai_outline_doc", "document_id"),
        Index("ix_ai_outline_struct", "structure_id"),
        Index("ix_ai_outline_parent", "parent_outline_id"),
        Index("ix_ai_outline_created", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    structure_run_id: Mapped[int] = mapped_column(
        ForeignKey("ai_training_structure_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_id: Mapped[int] = mapped_column(
        ForeignKey("ai_training_documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    structure_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    parent_outline_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    numbering_text: Mapped[str | None] = mapped_column(String(64), nullable=True)
    outline_level: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    sequence_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class AiTrainingStructureEvent(Base):
    __tablename__ = "ai_training_structure_events"
    __table_args__ = (
        Index("ix_ai_struct_evt_doc", "document_id"),
        Index("ix_ai_struct_evt_run", "structure_run_id"),
        Index("ix_ai_struct_evt_type", "event_type"),
        Index("ix_ai_struct_evt_created", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("ai_training_documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    structure_run_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    workflow_run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    agent_run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    severity: Mapped[str] = mapped_column(String(32), nullable=False, default="info")
    message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    details_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
