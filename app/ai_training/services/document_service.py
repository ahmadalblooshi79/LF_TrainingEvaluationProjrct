"""رفع وتخزين وثائق التدريب."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.ai_agentic.json_util import dumps_json
from app.ai_agentic.services.audit_log_service import AuditLogService
from app.ai_training import config as cfg
from app.ai_training.constants import (
    APR_NOT_APPROVED,
    DOC_UPLOADED,
    DOCUMENT_TYPE_KEYS,
    EXT_NOT_STARTED,
    REV_NOT_REVIEWED,
)
from app.ai_training.exceptions import (
    DocumentAlreadyApprovedError,
    DocumentNotFoundError,
    DocumentStorageError,
    DuplicateDocumentError,
)
from app.ai_training.models import AiTrainingDocument, AiTrainingDocumentEvent
from app.ai_training.paths import document_extracted_dir, document_original_dir
from app.ai_training.security_upload import (
    sanitize_filename,
    sha256_bytes,
    sniff_file_type,
    validate_upload_filename,
    validate_upload_size,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class DocumentService:
    def __init__(self, db: Session):
        self.db = db
        self.audit = AuditLogService(db)

    def get_by_id(self, document_id: int) -> AiTrainingDocument:
        row = self.db.get(AiTrainingDocument, int(document_id))
        if not row:
            raise DocumentNotFoundError()
        return row

    def get_by_uuid(self, document_uuid: str) -> AiTrainingDocument:
        row = (
            self.db.query(AiTrainingDocument)
            .filter(AiTrainingDocument.document_uuid == document_uuid)
            .first()
        )
        if not row:
            raise DocumentNotFoundError()
        return row

    def list_documents(self, *, limit: int = 100, status: str | None = None) -> list[AiTrainingDocument]:
        q = self.db.query(AiTrainingDocument)
        if status:
            q = q.filter(AiTrainingDocument.status == status)
        return q.order_by(AiTrainingDocument.id.desc()).limit(max(1, min(limit, 500))).all()

    def emit_event(
        self,
        document_id: int,
        event_type: str,
        message: str,
        *,
        severity: str = "info",
        details: Any = None,
        workflow_run_id: int | None = None,
        agent_run_id: int | None = None,
    ) -> None:
        self.db.add(
            AiTrainingDocumentEvent(
                document_id=document_id,
                workflow_run_id=workflow_run_id,
                agent_run_id=agent_run_id,
                event_type=event_type,
                severity=severity,
                message=message or "",
                details_json=dumps_json(details),
                created_at=_utcnow(),
            )
        )
        self.db.commit()

    def upload(
        self,
        *,
        file_bytes: bytes,
        original_filename: str,
        title: str,
        document_type: str = "other",
        description: str = "",
        source_organization: str = "",
        document_date: str = "",
        language: str = "ar",
        version_number: int = 1,
        version_label: str = "",
        document_group_uuid: str | None = None,
        user_id: int | None = None,
    ) -> AiTrainingDocument:
        validate_upload_size(len(file_bytes))
        ext = validate_upload_filename(original_filename)
        kind, mime = sniff_file_type(file_bytes, ext)
        digest = sha256_bytes(file_bytes)

        existing = (
            self.db.query(AiTrainingDocument)
            .filter(AiTrainingDocument.sha256_hash == digest)
            .order_by(AiTrainingDocument.id.desc())
            .first()
        )
        if existing and cfg.AI_INGESTION_DUPLICATE_POLICY == "reject":
            raise DuplicateDocumentError(f"ملف مكرر — Document ID {existing.id}")

        dtype = (document_type or "other").strip()
        if dtype not in DOCUMENT_TYPE_KEYS:
            dtype = "other"

        doc_uuid = uuid.uuid4().hex
        group_uuid = (document_group_uuid or "").strip() or uuid.uuid4().hex
        safe_name = sanitize_filename(original_filename)
        stored_name = f"{doc_uuid}{ext}"
        dest_dir = document_original_dir(doc_uuid)
        dest_path = dest_dir / stored_name
        try:
            dest_path.write_bytes(file_bytes)
        except OSError as exc:
            raise DocumentStorageError("تعذر كتابة الملف على القرص.") from exc

        # تحقق مسار داخل الجذر
        try:
            dest_path.resolve().relative_to(dest_dir.resolve())
        except ValueError as exc:
            dest_path.unlink(missing_ok=True)
            raise DocumentStorageError("مسار تخزين غير آمن.") from exc

        row = AiTrainingDocument(
            document_uuid=doc_uuid,
            document_group_uuid=group_uuid,
            title=(title or safe_name).strip()[:512],
            original_filename=safe_name,
            stored_filename=stored_name,
            storage_path=str(dest_path),
            document_type=dtype,
            description=(description or None),
            source_organization=(source_organization or None),
            document_date=(document_date or None),
            language=(language or "ar")[:16],
            version_number=max(1, int(version_number or 1)),
            version_label=(version_label or None),
            is_latest_version=True,
            mime_type=mime,
            file_extension=ext,
            file_size_bytes=len(file_bytes),
            sha256_hash=digest,
            status=DOC_UPLOADED,
            extraction_status=EXT_NOT_STARTED,
            review_status=REV_NOT_REVIEWED,
            approval_status=APR_NOT_APPROVED,
            uploaded_by_user_id=user_id,
            created_at=_utcnow(),
            updated_at=_utcnow(),
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)

        if existing and cfg.AI_INGESTION_DUPLICATE_POLICY == "warn":
            self.emit_event(
                row.id,
                "document.duplicate_warning",
                f"بصمة SHA-256 مطابقة لوثيقة سابقة #{existing.id}",
                severity="warning",
                details={"previous_document_id": existing.id},
            )

        self.audit.log(
            action_type="training.document.upload",
            entity_type="ai_training_document",
            entity_id=str(row.id),
            user_id=user_id,
            new_value={"document_uuid": row.document_uuid, "sha256": digest, "ext": ext},
        )
        self.emit_event(row.id, "document.uploaded", "تم رفع الوثيقة وحفظ الأصل.")
        return row

    def assert_editable(self, doc: AiTrainingDocument) -> None:
        if doc.approval_status == "APPROVED_EXTRACTION" or doc.review_locked:
            raise DocumentAlreadyApprovedError()

    def document_to_dict(self, doc: AiTrainingDocument) -> dict[str, Any]:
        from app.ai_training.constants import label_ar
        from app.ai_training.structure_constants import structure_label_ar

        return {
            "id": doc.id,
            "document_uuid": doc.document_uuid,
            "document_group_uuid": doc.document_group_uuid,
            "title": doc.title,
            "original_filename": doc.original_filename,
            "document_type": doc.document_type,
            "description": doc.description,
            "source_organization": doc.source_organization,
            "document_date": doc.document_date,
            "language": doc.language,
            "version_number": doc.version_number,
            "version_label": doc.version_label,
            "is_latest_version": doc.is_latest_version,
            "mime_type": doc.mime_type,
            "file_extension": doc.file_extension,
            "file_size_bytes": doc.file_size_bytes,
            "sha256_hash": doc.sha256_hash,
            "page_count": doc.page_count,
            "paragraph_count": doc.paragraph_count,
            "table_count": doc.table_count,
            "status": doc.status,
            "status_ar": label_ar(doc.status),
            "extraction_status": doc.extraction_status,
            "extraction_status_ar": label_ar(doc.extraction_status),
            "review_status": doc.review_status,
            "review_status_ar": label_ar(doc.review_status),
            "approval_status": doc.approval_status,
            "approval_status_ar": label_ar(doc.approval_status),
            "structure_status": getattr(doc, "structure_status", None) or "NOT_STARTED",
            "structure_status_ar": structure_label_ar(getattr(doc, "structure_status", None) or "NOT_STARTED"),
            "latest_structure_run_id": getattr(doc, "latest_structure_run_id", None),
            "structure_locked": bool(getattr(doc, "structure_locked", False)),
            "uploaded_by_user_id": doc.uploaded_by_user_id,
            "latest_workflow_run_id": doc.latest_workflow_run_id,
            "review_locked": bool(doc.review_locked),
            "created_at": doc.created_at.isoformat(sep=" ", timespec="seconds") if doc.created_at else None,
            "updated_at": doc.updated_at.isoformat(sep=" ", timespec="seconds") if doc.updated_at else None,
            "approved_at": doc.approved_at.isoformat(sep=" ", timespec="seconds") if doc.approved_at else None,
            "structure_approved_at": (
                doc.structure_approved_at.isoformat(sep=" ", timespec="seconds")
                if getattr(doc, "structure_approved_at", None)
                else None
            ),
        }

    def save_extraction_json(self, doc: AiTrainingDocument, payload: dict[str, Any]) -> Path:
        out_dir = document_extracted_dir(doc.document_uuid)
        path = out_dir / "extracted.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path
