"""مسارات مركز التدريب — تُسجَّل على blueprint views."""

from __future__ import annotations

from flask import g, jsonify, redirect, render_template, request, send_file, url_for
from urllib.parse import quote

from app.ai_training import config as training_cfg
from app.ai_training.constants import DOCUMENT_TYPES, label_ar
from app.ai_training.exceptions import TrainingCenterError
from app.ai_training.models import (
    AiTrainingDocumentEvent,
    AiTrainingDocumentPage,
)
from app.ai_training.services.document_service import DocumentService
from app.ai_training.services.ingestion_service import IngestionService
from app.ai_training.services.review_service import ReviewService
from app.ai_agentic.services.audit_log_service import AuditLogService
from app.permissions import (
    can_ai_training_center_view,
    can_ai_training_document_approve,
    can_ai_training_document_archive,
    can_ai_training_document_review,
    can_ai_training_document_upload,
    can_ai_training_workflow_run,
    can_ai_structure_analyze,
    can_ai_structure_approve,
    can_ai_structure_audit_view,
    can_ai_structure_reanalyze,
    can_ai_structure_review,
    can_ai_structure_view,
)


def _json_err(exc: Exception, status: int = 400):
    if isinstance(exc, TrainingCenterError):
        return jsonify({"ok": False, "error": exc.error_code, "error_message": exc.user_message}), status
    return jsonify({"ok": False, "error": "server_error", "error_message": "تعذر إكمال الطلب."}), 500


def register_training_routes(bp, *, get_current_user_optional, abort, _ctx):
    def _user(*, upload=False, review=False, approve=False, archive=False, run=False):
        user = get_current_user_optional()
        if not user:
            return None, (jsonify({"ok": False, "error": "unauthorized"}), 401)
        if not can_ai_training_center_view(user):
            return None, (jsonify({"ok": False, "error": "forbidden"}), 403)
        if upload and not can_ai_training_document_upload(user):
            return None, (jsonify({"ok": False, "error": "forbidden"}), 403)
        if review and not can_ai_training_document_review(user):
            return None, (jsonify({"ok": False, "error": "forbidden"}), 403)
        if approve and not can_ai_training_document_approve(user):
            return None, (jsonify({"ok": False, "error": "forbidden"}), 403)
        if archive and not can_ai_training_document_archive(user):
            return None, (jsonify({"ok": False, "error": "forbidden"}), 403)
        if run and not can_ai_training_workflow_run(user):
            return None, (jsonify({"ok": False, "error": "forbidden"}), 403)
        return user, None

    @bp.route("/ai-center/training")
    def ai_training_center():
        user = get_current_user_optional()
        if not user:
            return redirect("/login?next=/ai-center/training")
        if not can_ai_training_center_view(user):
            abort(403)
        svc = DocumentService(g.db)
        docs = svc.list_documents(limit=100)
        counts = {
            "total": len(docs),
            "needs_review": sum(1 for d in docs if d.status == "NEEDS_REVIEW"),
            "approved": sum(1 for d in docs if d.approval_status == "APPROVED_EXTRACTION"),
            "failed": sum(1 for d in docs if d.status == "FAILED"),
            "processing": sum(1 for d in docs if d.status in ("QUEUED", "PROCESSING")),
        }
        return render_template(
            "ai_training_center.html",
            **_ctx(
                user,
                documents=[svc.document_to_dict(d) for d in docs],
                counts=counts,
                document_types=DOCUMENT_TYPES,
                can_upload=can_ai_training_document_upload(user),
                can_review=can_ai_training_document_review(user),
                can_approve=can_ai_training_document_approve(user),
                can_run=can_ai_training_workflow_run(user),
                error=request.args.get("err"),
                ok_msg=request.args.get("ok"),
            ),
        )

    @bp.route("/ai-center/training/upload", methods=["GET", "POST"])
    def ai_training_upload():
        user = get_current_user_optional()
        if not user:
            return redirect("/login?next=/ai-center/training/upload")
        if not can_ai_training_document_upload(user):
            abort(403)
        if request.method == "GET":
            return render_template(
                "ai_training_upload.html",
                **_ctx(user, document_types=DOCUMENT_TYPES, auto_ingest=training_cfg.AI_TRAINING_AUTO_INGEST),
            )
        f = request.files.get("file")
        if not f or not f.filename:
            return redirect("/ai-center/training/upload?err=" + quote("اختر ملفاً"))
        data = f.read()
        start_ingest = request.form.get("start_ingest") == "1" or (
            request.form.get("start_ingest") is None and training_cfg.AI_TRAINING_AUTO_INGEST
        )
        # checkbox: if present and value 1
        if "start_ingest" in request.form:
            start_ingest = request.form.get("start_ingest") == "1"
        try:
            svc = DocumentService(g.db)
            doc = svc.upload(
                file_bytes=data,
                original_filename=f.filename,
                title=(request.form.get("title") or "").strip(),
                document_type=(request.form.get("document_type") or "other").strip(),
                description=(request.form.get("description") or "").strip(),
                source_organization=(request.form.get("source_organization") or "").strip(),
                document_date=(request.form.get("document_date") or "").strip(),
                language=(request.form.get("language") or "ar").strip(),
                version_number=int(request.form.get("version_number") or 1),
                version_label=(request.form.get("version_label") or "").strip(),
                user_id=user.id,
            )
            if start_ingest and can_ai_training_workflow_run(user):
                IngestionService(g.db).queue_and_run_workflow(doc.id, user_id=user.id)
                return redirect(
                    f"/ai-center/training/documents/{doc.id}?ok=" + quote("تم الرفع وبدء الاستخراج")
                )
            return redirect(f"/ai-center/training/documents/{doc.id}?ok=" + quote("تم الرفع"))
        except TrainingCenterError as exc:
            return redirect("/ai-center/training/upload?err=" + quote(exc.user_message))
        except Exception:
            return redirect("/ai-center/training/upload?err=" + quote("فشل الرفع"))

    @bp.route("/ai-center/training/documents/<int:document_id>")
    def ai_training_document_detail(document_id: int):
        user = get_current_user_optional()
        if not user:
            return redirect(f"/login?next=/ai-center/training/documents/{document_id}")
        if not can_ai_training_center_view(user):
            abort(403)
        svc = DocumentService(g.db)
        try:
            doc = svc.get_by_id(document_id)
        except TrainingCenterError:
            abort(404)
        events = (
            g.db.query(AiTrainingDocumentEvent)
            .filter(AiTrainingDocumentEvent.document_id == document_id)
            .order_by(AiTrainingDocumentEvent.id.desc())
            .limit(50)
            .all()
        )
        pages = (
            g.db.query(AiTrainingDocumentPage)
            .filter(AiTrainingDocumentPage.document_id == document_id)
            .order_by(AiTrainingDocumentPage.page_number.asc(), AiTrainingDocumentPage.id.asc())
            .all()
        )
        blocks = ReviewService(g.db).list_blocks(document_id)
        from app.ai_training.models import AiTrainingDocument

        versions = (
            g.db.query(AiTrainingDocument)
            .filter(AiTrainingDocument.document_group_uuid == doc.document_group_uuid)
            .order_by(AiTrainingDocument.version_number.asc())
            .all()
        )
        return render_template(
            "ai_training_document_detail.html",
            **_ctx(
                user,
                document=svc.document_to_dict(doc),
                events=events,
                pages=pages,
                blocks=blocks,
                versions=[svc.document_to_dict(v) for v in versions],
                can_run=can_ai_training_workflow_run(user),
                can_review=can_ai_training_document_review(user),
                can_approve=can_ai_training_document_approve(user),
                can_archive=can_ai_training_document_archive(user),
                can_structure_view=can_ai_structure_view(user),
                can_structure_analyze=can_ai_structure_analyze(user),
                can_structure_review=can_ai_structure_review(user),
                can_structure_approve=can_ai_structure_approve(user),
                can_structure_reanalyze=can_ai_structure_reanalyze(user),
                error=request.args.get("err"),
                ok_msg=request.args.get("ok"),
            ),
        )

    @bp.route("/ai-center/training/documents/<int:document_id>/review", methods=["GET", "POST"])
    def ai_training_document_review(document_id: int):
        user = get_current_user_optional()
        if not user:
            return redirect(f"/login?next=/ai-center/training/documents/{document_id}/review")
        if not can_ai_training_document_review(user):
            abort(403)
        svc = DocumentService(g.db)
        rev = ReviewService(g.db)
        try:
            doc = svc.get_by_id(document_id)
        except TrainingCenterError:
            abort(404)
        if request.method == "POST":
            action = (request.form.get("action") or "save").strip()
            try:
                if action == "start":
                    rev.start_review(document_id, user_id=user.id)
                elif action == "save":
                    block_id = request.form.get("block_id")
                    text = request.form.get("text_content")
                    btype = request.form.get("block_type")
                    corrections = []
                    if block_id:
                        corrections.append(
                            {
                                "correction_type": "TEXT_CORRECTION",
                                "block_id": int(block_id),
                                "original_value": {},
                                "corrected_value": {
                                    "text_content": text,
                                    "block_type": btype,
                                },
                                "reason": request.form.get("reason") or "",
                            }
                        )
                    rev.save_corrections(
                        document_id,
                        corrections,
                        notes=request.form.get("review_notes"),
                        user_id=user.id,
                    )
                elif action == "complete":
                    rev.complete_review(document_id, user_id=user.id)
                    return redirect(
                        f"/ai-center/training/documents/{document_id}/review?ok=" + quote("اكتملت المراجعة")
                    )
                elif action == "approve":
                    if not can_ai_training_document_approve(user):
                        abort(403)
                    rev.approve_extraction(document_id, user_id=user.id)
                    return redirect(
                        f"/ai-center/training/documents/{document_id}?ok="
                        + quote("تم اعتماد جودة الاستخراج")
                    )
                return redirect(f"/ai-center/training/documents/{document_id}/review?ok=" + quote("تم الحفظ"))
            except TrainingCenterError as exc:
                return redirect(
                    f"/ai-center/training/documents/{document_id}/review?err=" + quote(exc.user_message)
                )
        blocks = rev.list_blocks(document_id)
        pages = (
            g.db.query(AiTrainingDocumentPage)
            .filter(AiTrainingDocumentPage.document_id == document_id)
            .order_by(AiTrainingDocumentPage.page_number.asc(), AiTrainingDocumentPage.id.asc())
            .all()
        )
        from app.ai_agentic.json_util import loads_json

        page_by_id = {p.id: p for p in pages}
        workspace_blocks = []
        for b in blocks:
            page = page_by_id.get(b.page_id) if b.page_id else None
            pn = page.page_number if page and page.page_number is not None else None
            workspace_blocks.append(
                {
                    "id": b.id,
                    "block_index": b.block_index,
                    "block_type": (b.block_type or "paragraph"),
                    "text_content": b.text_content or "",
                    "original_text": b.original_text or "",
                    "heading_level": int(b.heading_level or 1),
                    "list_level": int(b.list_level or 0) if b.list_level is not None else 0,
                    "numbering_text": b.numbering_text or "",
                    "page_id": b.page_id,
                    "page_number": pn,
                    "page_label": (page.page_label if page else None)
                    or (str(pn) if pn is not None else None),
                    "style_name": b.style_name or "",
                    "source_reference": b.source_reference or "",
                    "extraction_confidence": b.extraction_confidence,
                    "extraction_method": (page.extraction_method if page else None) or "—",
                    "table_data": loads_json(b.table_data_json, default=None),
                    "metadata": loads_json(b.metadata_json, default={}) or {},
                }
            )
        # Presentation-only grouping for Word Review Mode (no schema change).
        from collections import OrderedDict

        grouped: OrderedDict[int, list] = OrderedDict()
        for wb in workspace_blocks:
            key = int(wb["page_number"]) if wb["page_number"] is not None else 1
            grouped.setdefault(key, []).append(wb)
        if not grouped:
            grouped[1] = []
        workspace_pages = []
        for pn, blist in grouped.items():
            label = None
            if blist:
                label = blist[0].get("page_label")
            if not label:
                for p in pages:
                    if p.page_number == pn:
                        label = p.page_label or str(pn)
                        break
            workspace_pages.append(
                {
                    "page_number": pn,
                    "page_label": label or str(pn),
                    "blocks": blist,
                }
            )
        meta_raw = (doc.extraction_metadata_json or "").lower()
        err_raw = (doc.error_json or "").upper()
        ocr_required = ("OCR_REQUIRED" in err_raw) or ("needs_ocr" in meta_raw and "true" in meta_raw)
        has_headings = any(b["block_type"] == "heading" for b in workspace_blocks)
        structure_by_block = {}
        try:
            from app.ai_training.structure.service import StructureService

            for s in StructureService(g.db).get_structures(document_id):
                if s.block_id is not None:
                    structure_by_block[int(s.block_id)] = {
                        "structure_id": s.id,
                        "detected_role": s.detected_role,
                        "numbering_text": s.numbering_text,
                        "numbering_level": s.numbering_level,
                        "indentation_level": s.indentation_level,
                        "is_heading": s.is_heading,
                        "confidence": s.confidence,
                        "warnings": loads_json(s.warnings_json, default=[]) or [],
                    }
        except Exception:
            structure_by_block = {}
        return render_template(
            "ai_training_review.html",
            **_ctx(
                user,
                document=svc.document_to_dict(doc),
                blocks=blocks,
                pages=pages,
                workspace_blocks=workspace_blocks,
                workspace_pages=workspace_pages,
                has_headings=has_headings,
                ocr_required=ocr_required,
                structure_by_block=structure_by_block,
                can_approve=can_ai_training_document_approve(user),
                error=request.args.get("err"),
                ok_msg=request.args.get("ok"),
            ),
        )

    @bp.route("/ai-center/training/documents/<int:document_id>/download")
    def ai_training_document_download(document_id: int):
        user = get_current_user_optional()
        if not user or not can_ai_training_center_view(user):
            abort(403)
        svc = DocumentService(g.db)
        doc = svc.get_by_id(document_id)
        AuditLogService(g.db).log(
            action_type="training.document.download",
            entity_type="ai_training_document",
            entity_id=str(doc.id),
            user_id=user.id,
        )
        return send_file(
            doc.storage_path,
            as_attachment=True,
            download_name=doc.original_filename or doc.stored_filename,
        )

    @bp.route("/ai-center/training/documents/<int:document_id>/ingest", methods=["POST"])
    def ai_training_document_ingest_form(document_id: int):
        user = get_current_user_optional()
        if not user or not can_ai_training_workflow_run(user):
            abort(403)
        try:
            IngestionService(g.db).queue_and_run_workflow(document_id, user_id=user.id)
            return redirect(f"/ai-center/training/documents/{document_id}?ok=" + quote("تم تشغيل الاستخراج"))
        except TrainingCenterError as exc:
            return redirect(f"/ai-center/training/documents/{document_id}?err=" + quote(exc.user_message))
        except Exception:
            return redirect(f"/ai-center/training/documents/{document_id}?err=" + quote("فشل الاستخراج"))

    # —— JSON APIs ——

    @bp.route("/api/ai/training/documents", methods=["GET"])
    def api_ai_training_documents_list():
        user, err = _user()
        if err:
            return err
        svc = DocumentService(g.db)
        return jsonify({"ok": True, "documents": [svc.document_to_dict(d) for d in svc.list_documents()]})

    @bp.route("/api/ai/training/documents", methods=["POST"])
    def api_ai_training_documents_create():
        user, err = _user(upload=True)
        if err:
            return err
        f = request.files.get("file")
        if not f:
            return jsonify({"ok": False, "error": "validation", "error_message": "الملف مطلوب."}), 400
        try:
            svc = DocumentService(g.db)
            doc = svc.upload(
                file_bytes=f.read(),
                original_filename=f.filename or "file",
                title=(request.form.get("title") or "").strip(),
                document_type=(request.form.get("document_type") or "other").strip(),
                description=(request.form.get("description") or "").strip(),
                source_organization=(request.form.get("source_organization") or "").strip(),
                document_date=(request.form.get("document_date") or "").strip(),
                language=(request.form.get("language") or "ar").strip(),
                version_number=int(request.form.get("version_number") or 1),
                version_label=(request.form.get("version_label") or "").strip(),
                user_id=user.id,
            )
            start = request.form.get("start_ingest", "1") == "1"
            workflow = None
            if start and can_ai_training_workflow_run(user):
                workflow = IngestionService(g.db).queue_and_run_workflow(doc.id, user_id=user.id)
            return jsonify(
                {
                    "ok": True,
                    "document": svc.document_to_dict(doc),
                    "workflow": (workflow or {}).get("workflow"),
                }
            ), 201
        except TrainingCenterError as exc:
            return _json_err(exc, 400)

    @bp.route("/api/ai/training/documents/<int:document_id>", methods=["GET"])
    def api_ai_training_document_get(document_id: int):
        user, err = _user()
        if err:
            return err
        try:
            svc = DocumentService(g.db)
            return jsonify({"ok": True, "document": svc.document_to_dict(svc.get_by_id(document_id))})
        except TrainingCenterError as exc:
            return _json_err(exc, 404)

    @bp.route("/api/ai/training/documents/<int:document_id>/ingest", methods=["POST"])
    def api_ai_training_document_ingest(document_id: int):
        user, err = _user(run=True)
        if err:
            return err
        try:
            result = IngestionService(g.db).queue_and_run_workflow(document_id, user_id=user.id)
            return jsonify({"ok": True, **result})
        except TrainingCenterError as exc:
            return _json_err(exc, 400)
        except Exception:
            return jsonify({"ok": False, "error": "server_error", "error_message": "فشل الاستخراج."}), 500

    @bp.route("/api/ai/training/documents/<int:document_id>/reingest", methods=["POST"])
    def api_ai_training_document_reingest(document_id: int):
        return api_ai_training_document_ingest(document_id)

    @bp.route("/api/ai/training/documents/<int:document_id>/pages", methods=["GET"])
    def api_ai_training_document_pages(document_id: int):
        user, err = _user()
        if err:
            return err
        pages = (
            g.db.query(AiTrainingDocumentPage)
            .filter(AiTrainingDocumentPage.document_id == document_id)
            .order_by(AiTrainingDocumentPage.page_number.asc())
            .all()
        )
        return jsonify(
            {
                "ok": True,
                "pages": [
                    {
                        "id": p.id,
                        "page_number": p.page_number,
                        "page_label": p.page_label,
                        "character_count": p.character_count,
                        "cleaned_text": p.cleaned_text,
                    }
                    for p in pages
                ],
            }
        )

    @bp.route("/api/ai/training/documents/<int:document_id>/blocks", methods=["GET"])
    def api_ai_training_document_blocks(document_id: int):
        user, err = _user()
        if err:
            return err
        blocks = ReviewService(g.db).list_blocks(document_id)
        return jsonify(
            {
                "ok": True,
                "blocks": [
                    {
                        "id": b.id,
                        "block_index": b.block_index,
                        "block_type": b.block_type,
                        "text_content": b.text_content,
                        "page_id": b.page_id,
                        "style_name": b.style_name,
                    }
                    for b in blocks
                ],
            }
        )

    @bp.route("/api/ai/training/documents/<int:document_id>/review/start", methods=["POST"])
    def api_ai_training_review_start(document_id: int):
        user, err = _user(review=True)
        if err:
            return err
        try:
            r = ReviewService(g.db).start_review(document_id, user_id=user.id)
            return jsonify({"ok": True, "review_id": r.id})
        except TrainingCenterError as exc:
            return _json_err(exc, 400)

    @bp.route("/api/ai/training/documents/<int:document_id>/review/save", methods=["POST"])
    def api_ai_training_review_save(document_id: int):
        user, err = _user(review=True)
        if err:
            return err
        payload = request.get_json(silent=True) or {}
        try:
            out = ReviewService(g.db).save_corrections(
                document_id,
                payload.get("corrections") or [],
                review_id=payload.get("review_id"),
                notes=payload.get("notes"),
                user_id=user.id,
            )
            return jsonify({"ok": True, **out})
        except TrainingCenterError as exc:
            return _json_err(exc, 400)

    @bp.route("/api/ai/training/documents/<int:document_id>/review/complete", methods=["POST"])
    def api_ai_training_review_complete(document_id: int):
        user, err = _user(review=True)
        if err:
            return err
        try:
            r = ReviewService(g.db).complete_review(document_id, user_id=user.id)
            return jsonify({"ok": True, "review_id": r.id})
        except TrainingCenterError as exc:
            return _json_err(exc, 400)

    @bp.route("/api/ai/training/documents/<int:document_id>/approve-extraction", methods=["POST"])
    def api_ai_training_approve_extraction(document_id: int):
        user, err = _user(approve=True)
        if err:
            return err
        try:
            doc = ReviewService(g.db).approve_extraction(document_id, user_id=user.id)
            return jsonify({"ok": True, "document": DocumentService(g.db).document_to_dict(doc)})
        except TrainingCenterError as exc:
            return _json_err(exc, 400)

    @bp.route("/api/ai/training/documents/<int:document_id>/archive", methods=["POST"])
    def api_ai_training_archive(document_id: int):
        user, err = _user(archive=True)
        if err:
            return err
        from datetime import datetime, timezone

        svc = DocumentService(g.db)
        try:
            doc = svc.get_by_id(document_id)
            doc.status = "ARCHIVED"
            doc.archived_at = datetime.now(timezone.utc).replace(tzinfo=None)
            g.db.commit()
            AuditLogService(g.db).log(
                action_type="training.document.archive",
                entity_type="ai_training_document",
                entity_id=str(doc.id),
                user_id=user.id,
            )
            return jsonify({"ok": True, "document": svc.document_to_dict(doc)})
        except TrainingCenterError as exc:
            return _json_err(exc, 404)

    @bp.route("/api/ai/training/documents/<int:document_id>/events", methods=["GET"])
    def api_ai_training_events(document_id: int):
        user, err = _user()
        if err:
            return err
        rows = (
            g.db.query(AiTrainingDocumentEvent)
            .filter(AiTrainingDocumentEvent.document_id == document_id)
            .order_by(AiTrainingDocumentEvent.id.desc())
            .limit(100)
            .all()
        )
        return jsonify(
            {
                "ok": True,
                "events": [
                    {
                        "id": e.id,
                        "event_type": e.event_type,
                        "severity": e.severity,
                        "message": e.message,
                        "created_at": e.created_at.isoformat(sep=" ", timespec="seconds")
                        if e.created_at
                        else None,
                    }
                    for e in rows
                ],
            }
        )

    @bp.route("/api/ai/training/documents/<int:document_id>/workflows", methods=["GET"])
    def api_ai_training_workflows(document_id: int):
        user, err = _user()
        if err:
            return err
        from app.ai_agentic.models import AiWorkflowRun
        from app.ai_agentic.services.agent_orchestrator_service import AgentOrchestratorService

        orch = AgentOrchestratorService(g.db)
        rows = (
            g.db.query(AiWorkflowRun)
            .filter(
                AiWorkflowRun.source_type == "training_document",
                AiWorkflowRun.source_id == str(document_id),
            )
            .order_by(AiWorkflowRun.id.desc())
            .limit(50)
            .all()
        )
        return jsonify({"ok": True, "workflows": [orch.workflow_to_dict(w) for w in rows]})

    # —— Phase B2.1 Military Structure ——

    def _structure_user(*, analyze=False, review=False, approve=False, reanalyze=False, audit=False):
        user = get_current_user_optional()
        if not user:
            return None, (jsonify({"ok": False, "error": "unauthorized"}), 401)
        if not can_ai_structure_view(user):
            return None, (jsonify({"ok": False, "error": "forbidden"}), 403)
        if analyze and not can_ai_structure_analyze(user):
            return None, (jsonify({"ok": False, "error": "forbidden"}), 403)
        if review and not can_ai_structure_review(user):
            return None, (jsonify({"ok": False, "error": "forbidden"}), 403)
        if approve and not can_ai_structure_approve(user):
            return None, (jsonify({"ok": False, "error": "forbidden"}), 403)
        if reanalyze and not can_ai_structure_reanalyze(user):
            return None, (jsonify({"ok": False, "error": "forbidden"}), 403)
        if audit and not can_ai_structure_audit_view(user):
            return None, (jsonify({"ok": False, "error": "forbidden"}), 403)
        return user, None

    @bp.route("/ai-center/training/documents/<int:document_id>/structure", methods=["GET", "POST"])
    def ai_training_document_structure(document_id: int):
        user = get_current_user_optional()
        if not user:
            return redirect(f"/login?next=/ai-center/training/documents/{document_id}/structure")
        if not can_ai_structure_view(user):
            abort(403)
        from app.ai_training.structure.service import StructureService

        svc = DocumentService(g.db)
        struct = StructureService(g.db)
        try:
            doc = svc.get_by_id(document_id)
        except TrainingCenterError:
            abort(404)

        if request.method == "POST":
            action = (request.form.get("action") or "").strip()
            try:
                if action == "analyze" and can_ai_structure_analyze(user):
                    struct.queue_and_run(
                        document_id,
                        user_id=user.id,
                        allow_review_completed=can_ai_structure_analyze(user),
                    )
                    return redirect(
                        f"/ai-center/training/documents/{document_id}/structure?ok="
                        + quote("اكتمل تحليل البنية")
                    )
                if action == "reanalyze" and can_ai_structure_reanalyze(user):
                    struct.queue_and_run(
                        document_id,
                        user_id=user.id,
                        reanalyze=True,
                        allow_review_completed=True,
                    )
                    return redirect(
                        f"/ai-center/training/documents/{document_id}/structure?ok="
                        + quote("اكتملت إعادة التحليل")
                    )
                if action == "start_review" and can_ai_structure_review(user):
                    struct.start_review(document_id, user_id=user.id)
                elif action == "save_review" and can_ai_structure_review(user):
                    import json as _json

                    raw = request.form.get("corrections_json") or "[]"
                    corrections = _json.loads(raw)
                    if isinstance(corrections, dict):
                        corrections = [corrections]
                    struct.save_review(document_id, corrections, user_id=user.id)
                elif action == "complete_review" and can_ai_structure_review(user):
                    struct.complete_review(document_id, user_id=user.id)
                elif action == "approve" and can_ai_structure_approve(user):
                    struct.approve_structure(document_id, user_id=user.id)
                    return redirect(
                        f"/ai-center/training/documents/{document_id}/structure?ok="
                        + quote("تم اعتماد البنية العسكرية")
                    )
                return redirect(f"/ai-center/training/documents/{document_id}/structure?ok=" + quote("تم الحفظ"))
            except TrainingCenterError as exc:
                return redirect(
                    f"/ai-center/training/documents/{document_id}/structure?err=" + quote(exc.user_message)
                )

        run = struct.latest_run(document_id)
        structures = struct.get_structures(document_id)
        outline = struct.get_outline(document_id)
        queue = struct.review_queue(document_id)
        blocks = ReviewService(g.db).list_blocks(document_id)
        return render_template(
            "ai_training_structure_review.html",
            **_ctx(
                user,
                document=svc.document_to_dict(doc),
                structure_run=struct.run_to_dict(run) if run else None,
                structures=[struct.structure_to_dict(s) for s in structures],
                outline=[struct.outline_to_dict(o) for o in outline],
                review_queue=queue,
                blocks=blocks,
                can_structure_analyze=can_ai_structure_analyze(user),
                can_structure_review=can_ai_structure_review(user),
                can_structure_approve=can_ai_structure_approve(user),
                can_structure_reanalyze=can_ai_structure_reanalyze(user),
                error=request.args.get("err"),
                ok_msg=request.args.get("ok"),
            ),
        )

    @bp.route("/api/ai/training/documents/<int:document_id>/structure/analyze", methods=["POST"])
    def api_ai_structure_analyze(document_id: int):
        user, err = _structure_user(analyze=True)
        if err:
            return err
        from app.ai_training.structure.service import StructureService

        try:
            result = StructureService(g.db).queue_and_run(
                document_id,
                user_id=user.id,
                allow_review_completed=True,
            )
            return jsonify({"ok": True, **result})
        except TrainingCenterError as exc:
            code = 400
            if exc.error_code == "structure_prerequisite":
                code = 409
            return _json_err(exc, code)

    @bp.route("/api/ai/training/documents/<int:document_id>/structure/reanalyze", methods=["POST"])
    def api_ai_structure_reanalyze(document_id: int):
        user, err = _structure_user(reanalyze=True)
        if err:
            return err
        from app.ai_training.structure.service import StructureService

        try:
            result = StructureService(g.db).queue_and_run(
                document_id,
                user_id=user.id,
                reanalyze=True,
                allow_review_completed=True,
            )
            return jsonify({"ok": True, **result})
        except TrainingCenterError as exc:
            return _json_err(exc, 400)

    @bp.route("/api/ai/training/documents/<int:document_id>/structure", methods=["GET"])
    def api_ai_structure_get(document_id: int):
        user, err = _structure_user()
        if err:
            return err
        from app.ai_training.structure.service import StructureService

        struct = StructureService(g.db)
        run = struct.latest_run(document_id)
        doc = DocumentService(g.db).document_to_dict(DocumentService(g.db).get_by_id(document_id))
        return jsonify(
            {
                "ok": True,
                "document": doc,
                "structure_run": struct.run_to_dict(run) if run else None,
                "structures": [struct.structure_to_dict(s) for s in struct.get_structures(document_id)],
            }
        )

    @bp.route("/api/ai/training/documents/<int:document_id>/structure/runs", methods=["GET"])
    def api_ai_structure_runs(document_id: int):
        user, err = _structure_user()
        if err:
            return err
        from app.ai_training.structure.service import StructureService

        struct = StructureService(g.db)
        return jsonify({"ok": True, "runs": [struct.run_to_dict(r) for r in struct.list_runs(document_id)]})

    @bp.route("/api/ai/training/documents/<int:document_id>/structure/outline", methods=["GET"])
    def api_ai_structure_outline(document_id: int):
        user, err = _structure_user()
        if err:
            return err
        from app.ai_training.structure.service import StructureService

        struct = StructureService(g.db)
        return jsonify({"ok": True, "outline": [struct.outline_to_dict(o) for o in struct.get_outline(document_id)]})

    @bp.route("/api/ai/training/documents/<int:document_id>/structure/review", methods=["GET"])
    def api_ai_structure_review_get(document_id: int):
        user, err = _structure_user(review=True)
        if err:
            return err
        from app.ai_training.structure.service import StructureService

        struct = StructureService(g.db)
        return jsonify(
            {
                "ok": True,
                "queue": struct.review_queue(document_id),
                "structures": [struct.structure_to_dict(s) for s in struct.get_structures(document_id)],
            }
        )

    @bp.route("/api/ai/training/documents/<int:document_id>/structure/review/start", methods=["POST"])
    def api_ai_structure_review_start(document_id: int):
        user, err = _structure_user(review=True)
        if err:
            return err
        from app.ai_training.structure.service import StructureService

        try:
            run = StructureService(g.db).start_review(document_id, user_id=user.id)
            return jsonify({"ok": True, "structure_run": StructureService(g.db).run_to_dict(run)})
        except TrainingCenterError as exc:
            return _json_err(exc, 400)

    @bp.route("/api/ai/training/documents/<int:document_id>/structure/review/save", methods=["POST"])
    def api_ai_structure_review_save(document_id: int):
        user, err = _structure_user(review=True)
        if err:
            return err
        from app.ai_training.structure.service import StructureService

        payload = request.get_json(silent=True) or {}
        corrections = payload.get("corrections") or []
        try:
            result = StructureService(g.db).save_review(document_id, corrections, user_id=user.id)
            return jsonify(result)
        except TrainingCenterError as exc:
            return _json_err(exc, 400)

    @bp.route("/api/ai/training/documents/<int:document_id>/structure/review/complete", methods=["POST"])
    def api_ai_structure_review_complete(document_id: int):
        user, err = _structure_user(review=True)
        if err:
            return err
        from app.ai_training.structure.service import StructureService

        try:
            run = StructureService(g.db).complete_review(document_id, user_id=user.id)
            return jsonify({"ok": True, "structure_run": StructureService(g.db).run_to_dict(run)})
        except TrainingCenterError as exc:
            return _json_err(exc, 400)

    @bp.route("/api/ai/training/documents/<int:document_id>/structure/approve", methods=["POST"])
    def api_ai_structure_approve(document_id: int):
        user, err = _structure_user(approve=True)
        if err:
            return err
        from app.ai_training.structure.service import StructureService

        try:
            run = StructureService(g.db).approve_structure(document_id, user_id=user.id)
            doc = DocumentService(g.db).get_by_id(document_id)
            return jsonify(
                {
                    "ok": True,
                    "structure_run": StructureService(g.db).run_to_dict(run),
                    "extraction_approval_status": doc.approval_status,
                }
            )
        except TrainingCenterError as exc:
            return _json_err(exc, 400)

    @bp.route("/api/ai/training/documents/<int:document_id>/structure/events", methods=["GET"])
    def api_ai_structure_events(document_id: int):
        user, err = _structure_user(audit=True)
        if err:
            return err
        from app.ai_training.structure.service import StructureService

        rows = StructureService(g.db).list_events(document_id)
        return jsonify(
            {
                "ok": True,
                "events": [
                    {
                        "id": e.id,
                        "event_type": e.event_type,
                        "severity": e.severity,
                        "message": e.message,
                        "structure_run_id": e.structure_run_id,
                        "created_at": e.created_at.isoformat(sep=" ", timespec="seconds")
                        if e.created_at
                        else None,
                    }
                    for e in rows
                ],
            }
        )
