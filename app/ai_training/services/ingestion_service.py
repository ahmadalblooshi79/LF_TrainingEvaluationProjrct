"""تشغيل الاستخراج وحفظ الصفحات والـ Blocks."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.ai_agentic.json_util import dumps_json
from app.ai_agentic.services.audit_log_service import AuditLogService, AiSystemEventService
from app.ai_training.constants import (
    DOC_FAILED,
    DOC_NEEDS_REVIEW,
    DOC_PROCESSING,
    DOC_QUEUED,
    EXT_FAILED,
    EXT_OCR_REQUIRED,
    EXT_PARTIAL_SUCCESS,
    EXT_RUNNING,
    EXT_SUCCESS,
    REV_NOT_REVIEWED,
)
from app.ai_training.exceptions import DocumentExtractionError, DocumentNotFoundError
from app.ai_training.extractors import get_extractor
from app.ai_training.extractors.base import ExtractionResult
from app.ai_training.models import (
    AiTrainingDocument,
    AiTrainingDocumentBlock,
    AiTrainingDocumentPage,
)
from app.ai_training.services.document_service import DocumentService


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class IngestionService:
    def __init__(self, db: Session):
        self.db = db
        self.docs = DocumentService(db)
        self.audit = AuditLogService(db)
        self.events = AiSystemEventService(db)

    def run_extraction(self, document_id: int, *, user_id: int | None = None) -> ExtractionResult:
        doc = self.docs.get_by_id(document_id)
        path = Path(doc.storage_path)
        if not path.is_file():
            raise DocumentExtractionError("ملف الأصل غير موجود على القرص.")

        doc.status = DOC_PROCESSING
        doc.extraction_status = EXT_RUNNING
        doc.updated_at = _utcnow()
        self.db.commit()

        # مسح نتائج سابقة عند إعادة الاستخراج
        self.db.query(AiTrainingDocumentBlock).filter(
            AiTrainingDocumentBlock.document_id == doc.id
        ).delete()
        self.db.query(AiTrainingDocumentPage).filter(
            AiTrainingDocumentPage.document_id == doc.id
        ).delete()
        self.db.commit()

        kind = (doc.file_extension or "").lstrip(".")
        extractor = get_extractor(kind)
        try:
            result = extractor.extract(path)
        except Exception as exc:  # noqa: BLE001
            doc.status = DOC_FAILED
            doc.extraction_status = EXT_FAILED
            doc.error_json = dumps_json([{"message": str(exc)}])
            doc.updated_at = _utcnow()
            self.db.commit()
            self.docs.emit_event(doc.id, "ingestion.failed", "فشل الاستخراج", severity="error")
            self.events.emit(
                event_type="training.ingestion_failed",
                severity="error",
                component="ingestion",
                message=str(exc),
                details={"document_id": doc.id},
            )
            raise DocumentExtractionError("فشل استخراج النص.") from exc

        # حفظ صفحات
        page_id_by_number: dict[int | None, int] = {}
        for p in result.pages:
            page = AiTrainingDocumentPage(
                document_id=doc.id,
                page_number=p.page_number,
                page_label=p.page_label,
                raw_text=p.raw_text,
                cleaned_text=p.cleaned_text,
                extraction_method=p.extraction_method,
                confidence=p.confidence,
                character_count=len(p.cleaned_text or ""),
                metadata_json=dumps_json(p.metadata),
                created_at=_utcnow(),
                updated_at=_utcnow(),
            )
            self.db.add(page)
            self.db.flush()
            page_id_by_number[p.page_number] = page.id

        for b in result.blocks:
            page_id = page_id_by_number.get(b.page_number)
            if page_id is None and page_id_by_number:
                # أول صفحة منطقية
                page_id = next(iter(page_id_by_number.values()))
            block = AiTrainingDocumentBlock(
                document_id=doc.id,
                page_id=page_id,
                block_index=b.block_index,
                block_type=b.block_type,
                text_content=b.text_content,
                original_text=b.original_text,
                style_name=b.style_name,
                heading_level=b.heading_level,
                list_level=b.list_level,
                numbering_text=b.numbering_text,
                bounding_box_json=dumps_json(b.bounding_box),
                table_data_json=dumps_json(b.table_data),
                source_reference=b.source_reference,
                extraction_confidence=b.extraction_confidence,
                metadata_json=dumps_json(b.metadata),
                created_at=_utcnow(),
                updated_at=_utcnow(),
            )
            self.db.add(block)

        extracted_path = self.docs.save_extraction_json(doc, result.to_dict())
        doc.extracted_text_path = str(extracted_path)
        doc.page_count = result.page_count
        doc.paragraph_count = result.paragraph_count
        doc.table_count = result.table_count
        doc.extraction_metadata_json = dumps_json(
            {**result.metadata, "warnings": result.warnings, "errors": result.errors}
        )
        doc.review_status = REV_NOT_REVIEWED
        doc.review_locked = False

        if result.status == EXT_OCR_REQUIRED:
            doc.extraction_status = EXT_PARTIAL_SUCCESS
            doc.status = DOC_NEEDS_REVIEW
            doc.error_json = dumps_json([{"code": "OCR_REQUIRED", "message": "يتطلب OCR لاحقاً"}])
        elif result.status == EXT_SUCCESS and result.blocks:
            doc.extraction_status = EXT_SUCCESS
            doc.status = DOC_NEEDS_REVIEW
            doc.error_json = None
        elif result.status == EXT_PARTIAL_SUCCESS:
            doc.extraction_status = EXT_PARTIAL_SUCCESS
            doc.status = DOC_NEEDS_REVIEW
        else:
            doc.extraction_status = EXT_FAILED
            doc.status = DOC_FAILED
            doc.error_json = dumps_json(result.errors or [{"message": "extraction failed"}])

        doc.updated_at = _utcnow()
        self.db.commit()

        self.docs.emit_event(
            doc.id,
            "ingestion.completed",
            f"انتهى الاستخراج: {doc.extraction_status}",
            severity="warning" if result.warnings else "info",
            details={"status": result.status, "blocks": len(result.blocks)},
        )
        self.audit.log(
            action_type="training.document.ingest",
            entity_type="ai_training_document",
            entity_id=str(doc.id),
            user_id=user_id,
            new_value={"extraction_status": doc.extraction_status, "blocks": len(result.blocks)},
        )
        return result

    def queue_and_run_workflow(self, document_id: int, *, user_id: int | None = None) -> dict[str, Any]:
        """إنشاء Workflow عبر Orchestrator وتشغيل Ingestion Agent."""
        from app.ai_agentic.constants import SYSTEM_HEALTH_AGENT_KEY  # noqa: F401
        from app.ai_agentic.services.agent_orchestrator_service import AgentOrchestratorService
        from app.ai_training.constants import DOCUMENT_INGESTION_AGENT_KEY, DOCUMENT_INGESTION_WORKFLOW_KEY

        doc = self.docs.get_by_id(document_id)
        doc.status = DOC_QUEUED
        doc.updated_at = _utcnow()
        self.db.commit()

        orch = AgentOrchestratorService(self.db)
        wf = orch.create_workflow_run(
            workflow_key=DOCUMENT_INGESTION_WORKFLOW_KEY,
            workflow_name="Document Ingestion",
            agent_keys=[DOCUMENT_INGESTION_AGENT_KEY],
            source_type="training_document",
            source_id=str(doc.id),
            user_id=user_id,
            metadata={"document_uuid": doc.document_uuid},
        )
        doc.latest_workflow_run_id = wf.id
        self.db.commit()

        wf = orch.start_workflow(
            wf.id,
            context={"document_id": doc.id},
            user_id=user_id,
        )
        self.db.refresh(doc)
        return {
            "document": self.docs.document_to_dict(doc),
            "workflow": orch.workflow_to_dict(wf),
        }
