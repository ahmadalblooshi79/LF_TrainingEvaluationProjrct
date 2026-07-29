"""خدمة تحليل/مراجعة/اعتماد البنية العسكرية."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.ai_agentic.json_util import dumps_json, loads_json
from app.ai_agentic.services.audit_log_service import AuditLogService
from app.ai_training import structure_config as scfg
from app.ai_training.constants import APR_APPROVED_EXTRACTION, DOC_APPROVED_EXTRACTION, REV_COMPLETED
from app.ai_training.exceptions import TrainingCenterError
from app.ai_training.models import (
    AiTrainingDocument,
    AiTrainingDocumentBlock,
    AiTrainingDocumentOutline,
    AiTrainingDocumentPage,
    AiTrainingDocumentStructure,
    AiTrainingStructureCorrection,
    AiTrainingStructureEvent,
    AiTrainingStructureRun,
)
from app.ai_training.structure.outline import build_outline_rows
from app.ai_training.structure_constants import (
    MILITARY_STRUCTURE_AGENT_KEY,
    MILITARY_STRUCTURE_PROMPT_VERSION,
    MILITARY_STRUCTURE_WORKFLOW_KEY,
    RV_CORRECTED,
    RV_PENDING,
    RUN_COMPLETED,
    RUN_COMPLETED_WITH_WARNINGS,
    RUN_FAILED,
    RUN_QUEUED,
    RUN_RUNNING,
    ST_APPROVED_STRUCTURE,
    ST_FAILED,
    ST_NEEDS_REVIEW,
    ST_NOT_STARTED,
    ST_QUEUED,
    ST_REVIEW_COMPLETED,
    ST_RUNNING,
    STRUCTURE_VERSION,
    structure_label_ar,
)

logger = logging.getLogger(__name__)


class StructurePrerequisiteError(TrainingCenterError):
    error_code = "structure_prerequisite"
    user_message = "يجب اعتماد جودة الاستخراج قبل بدء تحليل البنية العسكرية."


class StructureStateError(TrainingCenterError):
    error_code = "structure_state_error"
    user_message = "حالة تحليل البنية لا تسمح بهذه العملية."


class StructureLockedError(TrainingCenterError):
    error_code = "structure_locked"
    user_message = "نسخة البنية معتمدة ومقفلة. أعد التحليل لإنشاء مراجعة جديدة."


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class StructureService:
    def __init__(self, db: Session):
        self.db = db
        self.audit = AuditLogService(db)

    def emit_event(
        self,
        document_id: int,
        event_type: str,
        message: str,
        *,
        structure_run_id: int | None = None,
        workflow_run_id: int | None = None,
        agent_run_id: int | None = None,
        severity: str = "info",
        details: dict[str, Any] | None = None,
    ) -> None:
        self.db.add(
            AiTrainingStructureEvent(
                document_id=document_id,
                structure_run_id=structure_run_id,
                workflow_run_id=workflow_run_id,
                agent_run_id=agent_run_id,
                event_type=event_type,
                severity=severity,
                message=message,
                details_json=dumps_json(details or {}),
                created_at=_utcnow(),
            )
        )
        self.db.commit()

    def assert_can_analyze(self, doc: AiTrainingDocument) -> None:
        if doc.approval_status == APR_APPROVED_EXTRACTION or doc.status == DOC_APPROVED_EXTRACTION:
            return
        if doc.review_status == REV_COMPLETED:
            # allowed with appropriate permission — caller checks permission; default prefers approved
            return
        raise StructurePrerequisiteError()

    def assert_prefers_approved(self, doc: AiTrainingDocument, *, allow_review_completed: bool = False) -> None:
        if doc.approval_status == APR_APPROVED_EXTRACTION or doc.status == DOC_APPROVED_EXTRACTION:
            return
        if allow_review_completed and doc.review_status == REV_COMPLETED:
            return
        raise StructurePrerequisiteError()

    def get_document(self, document_id: int) -> AiTrainingDocument:
        doc = self.db.get(AiTrainingDocument, int(document_id))
        if not doc:
            raise TrainingCenterError("الوثيقة غير موجودة.")
        return doc

    def latest_run(self, document_id: int) -> AiTrainingStructureRun | None:
        return (
            self.db.query(AiTrainingStructureRun)
            .filter(AiTrainingStructureRun.document_id == document_id)
            .order_by(AiTrainingStructureRun.id.desc())
            .first()
        )

    def list_runs(self, document_id: int) -> list[AiTrainingStructureRun]:
        return (
            self.db.query(AiTrainingStructureRun)
            .filter(AiTrainingStructureRun.document_id == document_id)
            .order_by(AiTrainingStructureRun.id.desc())
            .all()
        )

    def _blocks_payload(self, document_id: int) -> list[dict[str, Any]]:
        pages = {
            p.id: p
            for p in self.db.query(AiTrainingDocumentPage)
            .filter(AiTrainingDocumentPage.document_id == document_id)
            .all()
        }
        blocks = (
            self.db.query(AiTrainingDocumentBlock)
            .filter(
                AiTrainingDocumentBlock.document_id == document_id,
                AiTrainingDocumentBlock.is_removed.is_(False),
            )
            .order_by(AiTrainingDocumentBlock.block_index.asc(), AiTrainingDocumentBlock.id.asc())
            .all()
        )
        out = []
        for b in blocks:
            page = pages.get(b.page_id) if b.page_id else None
            out.append(
                {
                    "id": b.id,
                    "block_index": b.block_index,
                    "block_type": b.block_type,
                    "text_content": b.text_content or "",
                    "original_text": b.original_text or "",
                    "style_name": b.style_name,
                    "heading_level": b.heading_level,
                    "list_level": b.list_level,
                    "numbering_text": b.numbering_text,
                    "page_number": page.page_number if page else None,
                    "metadata": loads_json(b.metadata_json, default={}) or {},
                }
            )
        return out

    def queue_and_run(
        self,
        document_id: int,
        *,
        user_id: int | None = None,
        reanalyze: bool = False,
        allow_review_completed: bool = False,
    ) -> dict[str, Any]:
        if not scfg.AI_STRUCTURE_ENABLED:
            raise StructureStateError("تحليل البنية معطّل.")
        doc = self.get_document(document_id)
        self.assert_prefers_approved(doc, allow_review_completed=allow_review_completed)

        if doc.structure_locked and not reanalyze:
            raise StructureLockedError()

        from app.ai_agentic.services.agent_orchestrator_service import AgentOrchestratorService

        orch = AgentOrchestratorService(self.db)
        wf = orch.create_workflow_run(
            workflow_key=MILITARY_STRUCTURE_WORKFLOW_KEY,
            workflow_name="Military Structure Analysis",
            agent_keys=[MILITARY_STRUCTURE_AGENT_KEY],
            source_type="training_document",
            source_id=str(document_id),
            user_id=user_id,
            model_name=scfg.AI_STRUCTURE_MODEL,
            metadata={"reanalyze": bool(reanalyze)},
        )

        run = AiTrainingStructureRun(
            document_id=doc.id,
            workflow_run_id=wf.id,
            status=RUN_QUEUED,
            structure_version=STRUCTURE_VERSION,
            model_name=scfg.AI_STRUCTURE_MODEL,
            prompt_version=MILITARY_STRUCTURE_PROMPT_VERSION,
            total_blocks=0,
            started_at=_utcnow(),
            is_locked=False,
            metadata_json=dumps_json({"reanalyze": bool(reanalyze)}),
            created_at=_utcnow(),
            updated_at=_utcnow(),
        )
        self.db.add(run)
        doc.structure_status = ST_QUEUED
        doc.structure_locked = False
        doc.latest_structure_run_id = None  # set after flush
        doc.updated_at = _utcnow()
        self.db.commit()
        self.db.refresh(run)
        doc.latest_structure_run_id = run.id
        doc.structure_status = ST_RUNNING
        run.status = RUN_RUNNING
        run.updated_at = _utcnow()
        self.db.commit()

        self.emit_event(doc.id, "structure.queued", "تم طابور تحليل البنية", structure_run_id=run.id, workflow_run_id=wf.id)
        self.audit.log(
            action_type="training.structure.analyze",
            entity_type="ai_training_document",
            entity_id=str(doc.id),
            user_id=user_id,
            workflow_run_id=wf.id,
            new_value={"structure_run_id": run.id, "reanalyze": reanalyze},
        )

        blocks = self._blocks_payload(doc.id)
        run.total_blocks = len(blocks)
        self.db.commit()

        # Do not put non-JSON callables into workflow context (input_json serialization).
        wf = orch.start_workflow(
            wf.id,
            context={
                "document_id": doc.id,
                "blocks": blocks,
                "structure_run_id": run.id,
            },
            user_id=user_id,
        )

        # Persist agent output into structure tables
        from app.ai_agentic.models import AiAgentRun

        agent_runs = (
            self.db.query(AiAgentRun)
            .filter(AiAgentRun.workflow_run_id == wf.id)
            .order_by(AiAgentRun.sequence_number.asc())
            .all()
        )
        output = {}
        if agent_runs:
            output = loads_json(agent_runs[-1].output_json, default={}) or {}
        data = (output.get("data") if isinstance(output, dict) else None) or output
        structures = list((data or {}).get("structures") or [])

        self._persist_structures(doc, run, structures, blocks)
        warnings = list((data or {}).get("validation", {}).get("warnings") or []) + list(output.get("warnings") or [])
        errors = list((data or {}).get("validation", {}).get("errors") or []) + list(output.get("errors") or [])
        low = int((data or {}).get("low_confidence_count") or 0)
        conflicts = int((data or {}).get("conflict_count") or 0)

        run.analyzed_blocks = len(structures)
        run.total_structures = len(structures)
        run.low_confidence_count = low
        run.conflict_count = conflicts
        run.completed_at = _utcnow()
        run.updated_at = _utcnow()
        run.knowledge_version = (data or {}).get("prompt_version")  # best-effort
        if errors or (output.get("status") == "failed"):
            run.status = RUN_FAILED
            run.error_json = dumps_json({"errors": errors})
            doc.structure_status = ST_FAILED
        else:
            run.status = RUN_COMPLETED_WITH_WARNINGS if warnings or low else RUN_COMPLETED
            doc.structure_status = ST_NEEDS_REVIEW
        doc.latest_structure_run_id = run.id
        doc.updated_at = _utcnow()
        self.db.commit()

        self.emit_event(
            doc.id,
            "structure.completed",
            "اكتمل تحليل البنية",
            structure_run_id=run.id,
            workflow_run_id=wf.id,
            details={"status": run.status, "structures": len(structures)},
        )
        return {
            "ok": run.status != RUN_FAILED,
            "structure_run": self.run_to_dict(run),
            "workflow": orch.workflow_to_dict(wf),
            "document_structure_status": doc.structure_status,
            "document_structure_status_ar": structure_label_ar(doc.structure_status),
        }

    def _persist_structures(
        self,
        doc: AiTrainingDocument,
        run: AiTrainingStructureRun,
        structures: list[dict[str, Any]],
        blocks: list[dict[str, Any]],
    ) -> None:
        # Clear previous rows for this run only (new run = new rows)
        page_map = {int(b["id"]): b.get("page_number") for b in blocks}

        # First pass: create structure rows without parent_structure_id
        block_to_struct: dict[int, AiTrainingDocumentStructure] = {}
        for s in structures:
            bid = int(s["block_id"]) if s.get("block_id") is not None else None
            row = AiTrainingDocumentStructure(
                structure_run_id=run.id,
                document_id=doc.id,
                block_id=bid,
                parent_structure_id=None,
                detected_role=s.get("detected_role") or "unknown",
                numbering_text=s.get("numbering_text"),
                numbering_style=s.get("numbering_style") or "none",
                numbering_level=s.get("numbering_level"),
                indentation_level=int(s.get("indentation_level") or 0),
                sequence_order=int(s.get("sequence_order") or 0),
                title_text=s.get("title_text"),
                content_text=s.get("content_text"),
                is_heading=bool(s.get("is_heading")),
                is_content=bool(s.get("is_content", not s.get("is_heading"))),
                confidence=s.get("confidence"),
                evidence_json=dumps_json(s.get("evidence") or []),
                warnings_json=dumps_json(s.get("warnings") or []),
                detection_source=s.get("detection_source") or "rule",
                rule_result_json=dumps_json(s.get("rule_result")) if s.get("rule_result") else None,
                llm_result_json=dumps_json(s.get("llm_result")) if s.get("llm_result") else None,
                reviewer_status=RV_PENDING,
                created_at=_utcnow(),
                updated_at=_utcnow(),
            )
            self.db.add(row)
            self.db.flush()
            if bid is not None:
                block_to_struct[bid] = row

        # Second pass: parent_structure_id from parent_block_id
        for s in structures:
            bid = int(s["block_id"]) if s.get("block_id") is not None else None
            parent_bid = s.get("parent_block_id")
            if bid is None or parent_bid is None:
                continue
            child = block_to_struct.get(bid)
            parent = block_to_struct.get(int(parent_bid))
            if child and parent:
                child.parent_structure_id = parent.id

        # Outline
        outline_rows = build_outline_rows(structures, block_page_map=page_map)
        temp_to_outline: dict[int, AiTrainingDocumentOutline] = {}
        for o in outline_rows:
            struct = block_to_struct.get(o["structure_block_id"]) if o.get("structure_block_id") else None
            row = AiTrainingDocumentOutline(
                structure_run_id=run.id,
                document_id=doc.id,
                structure_id=struct.id if struct else None,
                parent_outline_id=None,
                title=o["title"],
                numbering_text=o.get("numbering_text"),
                outline_level=int(o["outline_level"]),
                sequence_order=int(o["sequence_order"]),
                page_number=o.get("page_number"),
                created_at=_utcnow(),
                updated_at=_utcnow(),
            )
            self.db.add(row)
            self.db.flush()
            temp_to_outline[int(o["temp_key"])] = row
        for o in outline_rows:
            parent_key = o.get("parent_temp_key")
            if parent_key and o["temp_key"] in temp_to_outline and parent_key in temp_to_outline:
                temp_to_outline[o["temp_key"]].parent_outline_id = temp_to_outline[parent_key].id

        self.db.commit()

    def get_structures(self, document_id: int, *, run_id: int | None = None) -> list[AiTrainingDocumentStructure]:
        run = self.db.get(AiTrainingStructureRun, run_id) if run_id else self.latest_run(document_id)
        if not run:
            return []
        return (
            self.db.query(AiTrainingDocumentStructure)
            .filter(AiTrainingDocumentStructure.structure_run_id == run.id)
            .order_by(AiTrainingDocumentStructure.sequence_order.asc(), AiTrainingDocumentStructure.id.asc())
            .all()
        )

    def get_outline(self, document_id: int, *, run_id: int | None = None) -> list[AiTrainingDocumentOutline]:
        run = self.db.get(AiTrainingStructureRun, run_id) if run_id else self.latest_run(document_id)
        if not run:
            return []
        return (
            self.db.query(AiTrainingDocumentOutline)
            .filter(AiTrainingDocumentOutline.structure_run_id == run.id)
            .order_by(AiTrainingDocumentOutline.sequence_order.asc())
            .all()
        )

    def review_queue(self, document_id: int, *, run_id: int | None = None) -> list[dict[str, Any]]:
        rows = self.get_structures(document_id, run_id=run_id)
        medium = scfg.AI_STRUCTURE_CONFIDENCE_MEDIUM
        queue = []
        for r in rows:
            warns = loads_json(r.warnings_json, default=[]) or []
            conf = float(r.confidence) if r.confidence is not None else 0.0
            reasons = []
            if conf < medium:
                reasons.append("low_confidence")
            if r.detected_role == "unknown":
                reasons.append("unknown")
            for w in warns:
                if w in (
                    "rule_llm_conflict",
                    "duplicate_numbering",
                    "numbering_sequence_break",
                    "missing_parent",
                    "child_without_parent",
                ):
                    reasons.append(w)
            if r.numbering_level and int(r.numbering_level) > 1 and not r.parent_structure_id:
                reasons.append("missing_parent")
            if reasons:
                queue.append({**self.structure_to_dict(r), "queue_reasons": reasons})
        return queue

    def start_review(self, document_id: int, *, user_id: int | None = None) -> AiTrainingStructureRun:
        doc = self.get_document(document_id)
        run = self.latest_run(document_id)
        if not run:
            raise StructureStateError("لا يوجد تحليل بنية للمراجعة.")
        if run.is_locked or doc.structure_status == ST_APPROVED_STRUCTURE:
            raise StructureLockedError()
        if doc.structure_status not in (
            ST_NEEDS_REVIEW,
            ST_REVIEW_COMPLETED,
            ST_COMPLETED,
            ST_COMPLETED_WITH_WARNINGS,
        ):
            if run.status not in (RUN_COMPLETED, RUN_COMPLETED_WITH_WARNINGS):
                raise StructureStateError("لا يمكن بدء مراجعة البنية قبل اكتمال التحليل.")
        doc.structure_status = ST_NEEDS_REVIEW
        doc.updated_at = _utcnow()
        self.db.commit()
        self.emit_event(doc.id, "structure.review.start", "بدء مراجعة البنية", structure_run_id=run.id)
        self.audit.log(
            action_type="training.structure.review.start",
            entity_type="ai_training_document",
            entity_id=str(doc.id),
            user_id=user_id,
            new_value={"structure_run_id": run.id},
        )
        return run

    def save_review(
        self,
        document_id: int,
        corrections: list[dict[str, Any]],
        *,
        user_id: int | None = None,
    ) -> dict[str, Any]:
        doc = self.get_document(document_id)
        run = self.latest_run(document_id)
        if not run or run.is_locked:
            raise StructureLockedError()
        saved = 0
        for c in corrections:
            sid = c.get("structure_id")
            row = self.db.get(AiTrainingDocumentStructure, int(sid)) if sid else None
            if not row or row.structure_run_id != run.id:
                continue
            original = self.structure_to_dict(row)
            fields = (
                "detected_role",
                "numbering_text",
                "numbering_style",
                "numbering_level",
                "indentation_level",
                "is_heading",
                "title_text",
                "parent_structure_id",
            )
            changed = False
            for f in fields:
                if f in c:
                    setattr(row, f, c[f])
                    changed = True
            if "is_heading" in c:
                row.is_content = not bool(c["is_heading"])
            if changed:
                row.reviewer_status = RV_CORRECTED
                row.reviewer_notes = c.get("reason") or row.reviewer_notes
                row.updated_at = _utcnow()
                self.db.add(
                    AiTrainingStructureCorrection(
                        structure_run_id=run.id,
                        structure_id=row.id,
                        document_id=doc.id,
                        block_id=row.block_id,
                        correction_type=c.get("correction_type") or "STRUCTURE_CORRECTION",
                        original_value_json=dumps_json(original),
                        corrected_value_json=dumps_json(c),
                        reason=c.get("reason") or "",
                        corrected_by_user_id=user_id,
                        created_at=_utcnow(),
                        updated_at=_utcnow(),
                    )
                )
                saved += 1
        self.db.commit()
        self.emit_event(doc.id, "structure.review.save", f"حفظ {saved} تصحيحاً", structure_run_id=run.id)
        self.audit.log(
            action_type="training.structure.review.save",
            entity_type="ai_training_document",
            entity_id=str(doc.id),
            user_id=user_id,
            new_value={"saved": saved, "structure_run_id": run.id},
        )
        return {"ok": True, "saved": saved}

    def complete_review(self, document_id: int, *, user_id: int | None = None) -> AiTrainingStructureRun:
        doc = self.get_document(document_id)
        run = self.latest_run(document_id)
        if not run or run.is_locked:
            raise StructureLockedError()
        doc.structure_status = ST_REVIEW_COMPLETED
        doc.updated_at = _utcnow()
        self.db.commit()
        self.emit_event(doc.id, "structure.review.complete", "اكتملت مراجعة البنية", structure_run_id=run.id)
        self.audit.log(
            action_type="training.structure.review.complete",
            entity_type="ai_training_document",
            entity_id=str(doc.id),
            user_id=user_id,
            new_value={"structure_run_id": run.id},
        )
        return run

    def approve_structure(self, document_id: int, *, user_id: int | None = None) -> AiTrainingStructureRun:
        doc = self.get_document(document_id)
        run = self.latest_run(document_id)
        if not run:
            raise StructureStateError("لا يوجد تحليل للاعتماد.")
        if run.is_locked or doc.structure_status == ST_APPROVED_STRUCTURE:
            raise StructureLockedError()
        if doc.structure_status != ST_REVIEW_COMPLETED:
            raise StructureStateError("يجب إنهاء مراجعة البنية قبل الاعتماد.")

        # Snapshot extraction approval — must remain unchanged
        extraction_approval_before = doc.approval_status

        run.is_locked = True
        run.approved_by_user_id = user_id
        run.approved_at = _utcnow()
        run.updated_at = _utcnow()
        run.structure_version = STRUCTURE_VERSION
        doc.structure_status = ST_APPROVED_STRUCTURE
        doc.structure_locked = True
        doc.structure_approved_by_user_id = user_id
        doc.structure_approved_at = _utcnow()
        doc.updated_at = _utcnow()
        # NEVER touch extraction approval
        assert doc.approval_status == extraction_approval_before
        self.db.commit()

        self.emit_event(doc.id, "structure.approved", "تم اعتماد البنية العسكرية", structure_run_id=run.id)
        self.audit.log(
            action_type="training.structure.approve",
            entity_type="ai_training_document",
            entity_id=str(doc.id),
            user_id=user_id,
            new_value={
                "structure_run_id": run.id,
                "structure_version": STRUCTURE_VERSION,
                "extraction_approval_unchanged": extraction_approval_before,
            },
        )
        return run

    def list_events(self, document_id: int, *, limit: int = 100) -> list[AiTrainingStructureEvent]:
        return (
            self.db.query(AiTrainingStructureEvent)
            .filter(AiTrainingStructureEvent.document_id == document_id)
            .order_by(AiTrainingStructureEvent.id.desc())
            .limit(max(1, min(limit, 500)))
            .all()
        )

    def run_to_dict(self, run: AiTrainingStructureRun) -> dict[str, Any]:
        return {
            "id": run.id,
            "document_id": run.document_id,
            "workflow_run_id": run.workflow_run_id,
            "status": run.status,
            "structure_version": run.structure_version,
            "model_name": run.model_name,
            "prompt_version": run.prompt_version,
            "total_blocks": run.total_blocks,
            "analyzed_blocks": run.analyzed_blocks,
            "total_structures": run.total_structures,
            "low_confidence_count": run.low_confidence_count,
            "conflict_count": run.conflict_count,
            "is_locked": run.is_locked,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
            "approved_at": run.approved_at.isoformat() if run.approved_at else None,
        }

    def structure_to_dict(self, row: AiTrainingDocumentStructure) -> dict[str, Any]:
        return {
            "id": row.id,
            "structure_run_id": row.structure_run_id,
            "document_id": row.document_id,
            "block_id": row.block_id,
            "parent_structure_id": row.parent_structure_id,
            "detected_role": row.detected_role,
            "numbering_text": row.numbering_text,
            "numbering_style": row.numbering_style,
            "numbering_level": row.numbering_level,
            "indentation_level": row.indentation_level,
            "sequence_order": row.sequence_order,
            "title_text": row.title_text,
            "content_text": row.content_text,
            "is_heading": row.is_heading,
            "is_content": row.is_content,
            "confidence": row.confidence,
            "evidence": loads_json(row.evidence_json, default=[]) or [],
            "warnings": loads_json(row.warnings_json, default=[]) or [],
            "detection_source": row.detection_source,
            "reviewer_status": row.reviewer_status,
            "reviewer_notes": row.reviewer_notes,
        }

    def outline_to_dict(self, row: AiTrainingDocumentOutline) -> dict[str, Any]:
        return {
            "id": row.id,
            "structure_run_id": row.structure_run_id,
            "document_id": row.document_id,
            "structure_id": row.structure_id,
            "parent_outline_id": row.parent_outline_id,
            "title": row.title,
            "numbering_text": row.numbering_text,
            "outline_level": row.outline_level,
            "sequence_order": row.sequence_order,
            "page_number": row.page_number,
        }
