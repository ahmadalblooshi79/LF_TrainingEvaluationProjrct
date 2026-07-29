"""مراجعة واعتماد جودة الاستخراج."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.ai_agentic.json_util import dumps_json, loads_json
from app.ai_agentic.services.audit_log_service import AuditLogService
from app.ai_training.constants import (
    APR_APPROVED_EXTRACTION,
    DOC_APPROVED_EXTRACTION,
    DOC_NEEDS_REVIEW,
    DOC_REVIEWED,
    REV_COMPLETED,
    REV_IN_REVIEW,
)
from app.ai_training.exceptions import (
    DocumentAlreadyApprovedError,
    ExtractionApprovalError,
    ReviewStateError,
)
from app.ai_training.models import (
    AiTrainingDocumentBlock,
    AiTrainingDocumentCorrection,
    AiTrainingDocumentReview,
)
from app.ai_training.services.document_service import DocumentService


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class ReviewService:
    def __init__(self, db: Session):
        self.db = db
        self.docs = DocumentService(db)
        self.audit = AuditLogService(db)

    def start_review(self, document_id: int, *, user_id: int | None = None) -> AiTrainingDocumentReview:
        doc = self.docs.get_by_id(document_id)
        self.docs.assert_editable(doc)
        if doc.status not in (DOC_NEEDS_REVIEW, DOC_REVIEWED, "EXTRACTED", "REVIEWED"):
            if doc.extraction_status not in ("SUCCESS", "PARTIAL_SUCCESS", "OCR_REQUIRED"):
                raise ReviewStateError("لا يمكن بدء المراجعة قبل اكتمال الاستخراج.")
        review = AiTrainingDocumentReview(
            document_id=doc.id,
            reviewer_user_id=user_id,
            review_status=REV_IN_REVIEW,
            started_at=_utcnow(),
            created_at=_utcnow(),
            updated_at=_utcnow(),
        )
        self.db.add(review)
        doc.review_status = REV_IN_REVIEW
        doc.reviewed_by_user_id = user_id
        doc.updated_at = _utcnow()
        self.db.commit()
        self.db.refresh(review)
        self.audit.log(
            action_type="training.review.start",
            entity_type="ai_training_document",
            entity_id=str(doc.id),
            user_id=user_id,
            new_value={"review_id": review.id},
        )
        self.docs.emit_event(doc.id, "review.started", "بدأت مراجعة الاستخراج.")
        return review

    def save_corrections(
        self,
        document_id: int,
        corrections: list[dict[str, Any]],
        *,
        review_id: int | None = None,
        notes: str | None = None,
        user_id: int | None = None,
    ) -> dict[str, Any]:
        doc = self.docs.get_by_id(document_id)
        self.docs.assert_editable(doc)
        review = None
        if review_id:
            review = self.db.get(AiTrainingDocumentReview, review_id)
        if review is None:
            review = (
                self.db.query(AiTrainingDocumentReview)
                .filter(
                    AiTrainingDocumentReview.document_id == doc.id,
                    AiTrainingDocumentReview.is_locked.is_(False),
                )
                .order_by(AiTrainingDocumentReview.id.desc())
                .first()
            )
        if review is None:
            review = self.start_review(document_id, user_id=user_id)

        count = 0
        for item in corrections or []:
            ctype = (item.get("correction_type") or "OTHER").strip()
            block_id = item.get("block_id")
            block = self.db.get(AiTrainingDocumentBlock, int(block_id)) if block_id else None
            original = item.get("original_value")
            corrected = item.get("corrected_value") or {}
            if block and isinstance(corrected, dict):
                if "text_content" in corrected:
                    block.text_content = corrected.get("text_content")
                if "block_type" in corrected:
                    block.block_type = corrected.get("block_type") or block.block_type
                if corrected.get("is_removed"):
                    block.is_removed = True
                if "block_index" in corrected:
                    block.block_index = int(corrected["block_index"])
                block.updated_at = _utcnow()
            # إضافة Block جديد
            if ctype == "BLOCK_ADDED" and isinstance(corrected, dict):
                block = AiTrainingDocumentBlock(
                    document_id=doc.id,
                    page_id=corrected.get("page_id"),
                    block_index=int(corrected.get("block_index") or 0),
                    block_type=corrected.get("block_type") or "paragraph",
                    text_content=corrected.get("text_content") or "",
                    original_text=corrected.get("text_content") or "",
                    created_at=_utcnow(),
                    updated_at=_utcnow(),
                )
                self.db.add(block)
                self.db.flush()
                block_id = block.id

            self.db.add(
                AiTrainingDocumentCorrection(
                    document_id=doc.id,
                    block_id=int(block_id) if block_id else None,
                    review_id=review.id,
                    correction_type=ctype,
                    original_value_json=dumps_json(original),
                    corrected_value_json=dumps_json(corrected),
                    reason=item.get("reason"),
                    corrected_by_user_id=user_id,
                    created_at=_utcnow(),
                    updated_at=_utcnow(),
                )
            )
            count += 1

        if notes is not None:
            review.review_notes = notes
        review.corrected_blocks_count = int(review.corrected_blocks_count or 0) + count
        review.updated_at = _utcnow()
        doc.updated_at = _utcnow()
        self.db.commit()
        self.audit.log(
            action_type="training.review.save",
            entity_type="ai_training_document",
            entity_id=str(doc.id),
            user_id=user_id,
            new_value={"corrections": count, "review_id": review.id},
        )
        return {"ok": True, "saved": count, "review_id": review.id}

    def complete_review(self, document_id: int, *, review_id: int | None = None, user_id: int | None = None):
        doc = self.docs.get_by_id(document_id)
        self.docs.assert_editable(doc)
        review = None
        if review_id:
            review = self.db.get(AiTrainingDocumentReview, review_id)
        if review is None:
            review = (
                self.db.query(AiTrainingDocumentReview)
                .filter(AiTrainingDocumentReview.document_id == doc.id)
                .order_by(AiTrainingDocumentReview.id.desc())
                .first()
            )
        if not review:
            raise ReviewStateError("لا توجد مراجعة نشطة.")
        review.review_status = REV_COMPLETED
        review.completed_at = _utcnow()
        review.updated_at = _utcnow()
        doc.review_status = REV_COMPLETED
        doc.status = DOC_REVIEWED
        doc.reviewed_at = _utcnow()
        doc.reviewed_by_user_id = user_id
        doc.updated_at = _utcnow()
        self.db.commit()
        self.audit.log(
            action_type="training.review.complete",
            entity_type="ai_training_document",
            entity_id=str(doc.id),
            user_id=user_id,
            new_value={"review_id": review.id},
        )
        self.docs.emit_event(doc.id, "review.completed", "اكتملت مراجعة الاستخراج.")
        return review

    def approve_extraction(self, document_id: int, *, user_id: int | None = None):
        doc = self.docs.get_by_id(document_id)
        if doc.approval_status == APR_APPROVED_EXTRACTION:
            raise DocumentAlreadyApprovedError()
        if doc.review_status != REV_COMPLETED:
            raise ExtractionApprovalError("يجب إنهاء المراجعة قبل اعتماد جودة الاستخراج.")
        review = (
            self.db.query(AiTrainingDocumentReview)
            .filter(AiTrainingDocumentReview.document_id == doc.id)
            .order_by(AiTrainingDocumentReview.id.desc())
            .first()
        )
        if review:
            review.is_locked = True
            review.updated_at = _utcnow()
        doc.approval_status = APR_APPROVED_EXTRACTION
        doc.status = DOC_APPROVED_EXTRACTION
        doc.review_locked = True
        doc.approved_by_user_id = user_id
        doc.approved_at = _utcnow()
        doc.updated_at = _utcnow()
        self.db.commit()
        self.audit.log(
            action_type="training.document.approve_extraction",
            entity_type="ai_training_document",
            entity_id=str(doc.id),
            user_id=user_id,
            new_value={"approval_status": APR_APPROVED_EXTRACTION},
        )
        self.docs.emit_event(
            doc.id,
            "extraction.approved",
            "تم اعتماد جودة الاستخراج (بدون تعليم مؤسسي).",
        )
        return doc

    def list_blocks(self, document_id: int, *, include_removed: bool = False) -> list[AiTrainingDocumentBlock]:
        q = self.db.query(AiTrainingDocumentBlock).filter(
            AiTrainingDocumentBlock.document_id == document_id
        )
        if not include_removed:
            q = q.filter(AiTrainingDocumentBlock.is_removed.is_(False))
        return q.order_by(AiTrainingDocumentBlock.block_index.asc(), AiTrainingDocumentBlock.id.asc()).all()
