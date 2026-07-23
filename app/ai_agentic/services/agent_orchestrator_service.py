"""منسّق تشغيل الوكلاء وسير العمل."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.ai_agentic import config as ag_config
from app.ai_agentic.constants import (
    AR_CANCELLED,
    AR_FAILED,
    AR_PENDING,
    AR_SUCCESS,
    AR_WARNING,
    SYSTEM_HEALTH_AGENT_KEY,
    SYSTEM_HEALTH_WORKFLOW_KEY,
    WF_CANCELLED,
    WF_COMPLETED,
    WF_COMPLETED_WITH_WARNINGS,
    WF_CREATED,
    WF_FAILED,
    WF_PAUSED,
    WF_QUEUED,
    WF_RUNNING,
)
from app.ai_agentic.exceptions import (
    AgenticDisabledError,
    AgentDisabledError,
    WorkflowNotFoundError,
    WorkflowStateError,
)
from app.ai_agentic.json_util import dumps_json, loads_json
from app.ai_agentic.models import AiAgentRun, AiWorkflowRun
from app.ai_agentic.services.agent_execution_service import AgentExecutionService
from app.ai_agentic.services.agent_registry_service import AgentRegistryService
from app.ai_agentic.services.ai_gateway_service import AIGatewayService
from app.ai_agentic.services.audit_log_service import AuditLogService, AiSystemEventService
from app.ai_agentic.services.prompt_version_service import KnowledgeVersionService

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


_TERMINAL_WF = frozenset({WF_COMPLETED, WF_COMPLETED_WITH_WARNINGS, WF_FAILED, WF_CANCELLED})


class AgentOrchestratorService:
    def __init__(self, db: Session):
        self.db = db
        self.gateway = AIGatewayService(db)
        self.registry = AgentRegistryService(db)
        self.execution = AgentExecutionService(db, gateway=self.gateway)
        self.audit = AuditLogService(db)
        self.events = AiSystemEventService(db)
        self.knowledge = KnowledgeVersionService(db)

    def create_workflow_run(
        self,
        *,
        workflow_key: str,
        workflow_name: str,
        agent_keys: list[str],
        source_type: str | None = None,
        source_id: str | None = None,
        user_id: int | None = None,
        model_name: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AiWorkflowRun:
        if not ag_config.is_agentic_runtime_allowed():
            raise AgenticDisabledError()

        kv = self.knowledge.get_active()
        wf = AiWorkflowRun(
            workflow_key=workflow_key,
            workflow_name=workflow_name or workflow_key,
            source_type=source_type,
            source_id=source_id,
            requested_by_user_id=user_id,
            status=WF_CREATED,
            current_agent_key=agent_keys[0] if agent_keys else None,
            progress_percent=0,
            model_name=model_name,
            knowledge_version=kv.version if kv else None,
            metadata_json=dumps_json({"agent_keys": list(agent_keys), **(metadata or {})}),
            created_at=_utcnow(),
            updated_at=_utcnow(),
        )
        self.db.add(wf)
        self.db.commit()
        self.db.refresh(wf)

        for i, key in enumerate(agent_keys, start=1):
            agent = self.registry.get_agent(key)
            self.execution.create_pending_run(
                workflow_run_id=wf.id,
                agent_id=agent.id if agent else None,
                sequence_number=i,
            )

        self.audit.log(
            action_type="workflow.create",
            entity_type="ai_workflow_run",
            entity_id=str(wf.id),
            user_id=user_id,
            workflow_run_id=wf.id,
            new_value={"workflow_key": workflow_key, "agent_keys": agent_keys},
        )
        return wf

    def get_workflow(self, run_id: int) -> AiWorkflowRun:
        wf = self.db.get(AiWorkflowRun, int(run_id))
        if not wf:
            raise WorkflowNotFoundError()
        return wf

    def list_workflows(self, *, limit: int = 50) -> list[AiWorkflowRun]:
        return (
            self.db.query(AiWorkflowRun)
            .order_by(AiWorkflowRun.id.desc())
            .limit(max(1, min(limit, 200)))
            .all()
        )

    def agent_runs_for(self, workflow_run_id: int) -> list[AiAgentRun]:
        return (
            self.db.query(AiAgentRun)
            .filter(AiAgentRun.workflow_run_id == workflow_run_id)
            .order_by(AiAgentRun.sequence_number.asc(), AiAgentRun.id.asc())
            .all()
        )

    def start_workflow(
        self,
        run_id: int,
        *,
        context: dict[str, Any] | None = None,
        user_id: int | None = None,
    ) -> AiWorkflowRun:
        wf = self.get_workflow(run_id)
        if wf.status not in (WF_CREATED, WF_QUEUED, WF_PAUSED):
            if wf.status == WF_RUNNING:
                raise WorkflowStateError("سير العمل قيد التشغيل بالفعل.")
            if wf.status in _TERMINAL_WF:
                raise WorkflowStateError("لا يمكن بدء سير عمل منتهٍ.")
            raise WorkflowStateError()

        from app.ai_agentic.models import AiAgent

        meta = loads_json(wf.metadata_json, default={}) or {}
        agent_keys = list(meta.get("agent_keys") or [])
        if not agent_keys:
            for ar in self.agent_runs_for(wf.id):
                if ar.agent_id:
                    ag = self.db.get(AiAgent, ar.agent_id)
                    if ag:
                        agent_keys.append(ag.agent_key)

        wf.status = WF_QUEUED
        wf.updated_at = _utcnow()
        self.db.commit()

        wf.status = WF_RUNNING
        wf.started_at = wf.started_at or _utcnow()
        wf.updated_at = _utcnow()
        self.db.commit()

        self.audit.log(
            action_type="workflow.start",
            entity_type="ai_workflow_run",
            entity_id=str(wf.id),
            user_id=user_id,
            workflow_run_id=wf.id,
        )

        runs = self.agent_runs_for(wf.id)
        total = max(len(runs), 1)
        warnings = False
        ctx = dict(context or {})

        for idx, ar in enumerate(runs):
            # إعادة تحميل حالة الـ workflow للتحقق من pause/cancel
            self.db.refresh(wf)
            if wf.status == WF_PAUSED:
                return wf
            if wf.status == WF_CANCELLED:
                return wf

            from app.ai_agentic.models import AiAgent

            agent_key = None
            if ar.agent_id:
                ag = self.db.get(AiAgent, ar.agent_id)
                agent_key = ag.agent_key if ag else None
            if not agent_key and idx < len(agent_keys):
                agent_key = agent_keys[idx]
            if not agent_key:
                ar.status = AR_FAILED
                ar.error_json = dumps_json([{"message": "agent_key missing"}])
                self.db.commit()
                wf.status = WF_FAILED
                wf.error_message = "مفتاح وكيل مفقود"
                wf.completed_at = _utcnow()
                self.db.commit()
                return wf

            if ar.status in (AR_SUCCESS, AR_WARNING) and not ctx.get("force_all"):
                # تخطي الناجح عند الاستئناف
                continue

            wf.current_agent_key = agent_key
            wf.progress_percent = int((idx / total) * 100)
            wf.updated_at = _utcnow()
            self.db.commit()

            try:
                ar = self.execution.run_agent_row(ar, agent_key=agent_key, context=ctx)
            except AgentDisabledError as exc:
                ar.status = AR_FAILED
                ar.error_json = dumps_json([{"code": exc.error_code, "message": exc.user_message}])
                ar.completed_at = _utcnow()
                self.db.commit()
                wf.status = WF_FAILED
                wf.error_message = exc.user_message
                wf.completed_at = _utcnow()
                wf.updated_at = _utcnow()
                self.db.commit()
                return wf

            self.db.refresh(ar)
            if ar.status == AR_WARNING:
                warnings = True
            if ar.status == AR_FAILED:
                wf.status = WF_FAILED
                err = loads_json(ar.error_json, default=[])
                msg = ""
                if isinstance(err, list) and err:
                    msg = str(err[0].get("message") if isinstance(err[0], dict) else err[0])
                wf.error_message = msg or "فشل وكيل في المسار"
                wf.completed_at = _utcnow()
                wf.progress_percent = int(((idx + 1) / total) * 100)
                wf.updated_at = _utcnow()
                self.db.commit()
                self.events.emit(
                    event_type="workflow.failed",
                    severity="error",
                    component="orchestrator",
                    message=wf.error_message or "workflow failed",
                    workflow_run_id=wf.id,
                    agent_run_id=ar.id,
                )
                return wf

        self.db.refresh(wf)
        if wf.status == WF_CANCELLED:
            return wf
        if wf.status == WF_PAUSED:
            return wf

        final_runs = self.agent_runs_for(wf.id)
        ok_runs = [r for r in final_runs if r.status in (AR_SUCCESS, AR_WARNING)]
        if not ok_runs:
            wf.status = WF_FAILED
            wf.error_message = "لا يمكن إكمال المسار بنجاح دون حفظ Agent Run ناجح."
            wf.completed_at = _utcnow()
            wf.updated_at = _utcnow()
            self.db.commit()
            self.events.emit(
                event_type="workflow.persistence_failure",
                severity="error",
                component="orchestrator",
                message=wf.error_message,
                workflow_run_id=wf.id,
            )
            return wf

        wf.status = WF_COMPLETED_WITH_WARNINGS if warnings else WF_COMPLETED
        wf.progress_percent = 100
        wf.completed_at = _utcnow()
        wf.current_agent_key = None
        # انسخ نموذج/إصدارات من آخر agent run ناجح
        last_ok = ok_runs[-1]
        wf.model_name = last_ok.model_name or wf.model_name
        wf.prompt_version = last_ok.prompt_version or wf.prompt_version
        wf.knowledge_version = last_ok.knowledge_version or wf.knowledge_version
        wf.updated_at = _utcnow()
        self.db.commit()
        self.audit.log(
            action_type="workflow.complete",
            entity_type="ai_workflow_run",
            entity_id=str(wf.id),
            user_id=user_id,
            workflow_run_id=wf.id,
            new_value={"status": wf.status},
        )
        return wf

    def pause_workflow(self, run_id: int, *, user_id: int | None = None) -> AiWorkflowRun:
        wf = self.get_workflow(run_id)
        if wf.status != WF_RUNNING:
            raise WorkflowStateError("يمكن إيقاف سير العمل مؤقتاً أثناء RUNNING فقط.")
        wf.status = WF_PAUSED
        wf.updated_at = _utcnow()
        self.db.commit()
        self.audit.log(
            action_type="workflow.pause",
            entity_type="ai_workflow_run",
            entity_id=str(wf.id),
            user_id=user_id,
            workflow_run_id=wf.id,
        )
        return wf

    def resume_workflow(
        self,
        run_id: int,
        *,
        context: dict[str, Any] | None = None,
        user_id: int | None = None,
    ) -> AiWorkflowRun:
        wf = self.get_workflow(run_id)
        if wf.status != WF_PAUSED:
            raise WorkflowStateError("الاستئناف متاح لحالة PAUSED فقط.")
        self.audit.log(
            action_type="workflow.resume",
            entity_type="ai_workflow_run",
            entity_id=str(wf.id),
            user_id=user_id,
            workflow_run_id=wf.id,
        )
        return self.start_workflow(run_id, context=context, user_id=user_id)

    def cancel_workflow(self, run_id: int, *, user_id: int | None = None) -> AiWorkflowRun:
        wf = self.get_workflow(run_id)
        if wf.status in _TERMINAL_WF:
            raise WorkflowStateError("سير العمل منتهٍ مسبقاً.")
        wf.status = WF_CANCELLED
        wf.cancelled_at = _utcnow()
        wf.completed_at = wf.completed_at or _utcnow()
        wf.updated_at = _utcnow()
        for ar in self.agent_runs_for(wf.id):
            if ar.status in (AR_PENDING, "RUNNING", "RETRYING"):
                ar.status = AR_CANCELLED
                ar.completed_at = _utcnow()
                ar.updated_at = _utcnow()
        self.db.commit()
        self.audit.log(
            action_type="workflow.cancel",
            entity_type="ai_workflow_run",
            entity_id=str(wf.id),
            user_id=user_id,
            workflow_run_id=wf.id,
        )
        return wf

    def retry_workflow(
        self,
        run_id: int,
        *,
        context: dict[str, Any] | None = None,
        user_id: int | None = None,
    ) -> AiWorkflowRun:
        wf = self.get_workflow(run_id)
        if wf.status not in (WF_FAILED, WF_CANCELLED, WF_COMPLETED_WITH_WARNINGS):
            raise WorkflowStateError("إعادة المحاولة متاحة لحالات الفشل/الإلغاء/التحذيرات.")
        # إعادة ضبط الوكلاء الفاشلة فقط
        for ar in self.agent_runs_for(wf.id):
            if ar.status in (AR_FAILED, AR_CANCELLED):
                ar.status = AR_PENDING
                ar.attempt_number = 1
                ar.error_json = None
                ar.completed_at = None
                ar.duration_ms = None
                ar.updated_at = _utcnow()
        wf.status = WF_QUEUED
        wf.error_message = None
        wf.cancelled_at = None
        wf.completed_at = None
        wf.updated_at = _utcnow()
        self.db.commit()
        self.audit.log(
            action_type="workflow.retry",
            entity_type="ai_workflow_run",
            entity_id=str(wf.id),
            user_id=user_id,
            workflow_run_id=wf.id,
        )
        return self.start_workflow(run_id, context=context, user_id=user_id)

    def rerun_one_agent(
        self,
        run_id: int,
        agent_key: str,
        *,
        context: dict[str, Any] | None = None,
        user_id: int | None = None,
    ) -> AiWorkflowRun:
        wf = self.get_workflow(run_id)
        from app.ai_agentic.models import AiAgent

        agent = self.registry.get_agent_or_raise(agent_key)
        target = None
        for ar in self.agent_runs_for(wf.id):
            if ar.agent_id == agent.id:
                target = ar
                break
        if not target:
            raise WorkflowNotFoundError(f"لا يوجد تشغيل للوكيل {agent_key} في هذا المسار.")

        target.status = AR_PENDING
        target.attempt_number = 1
        target.error_json = None
        target.output_json = None
        target.completed_at = None
        target.updated_at = _utcnow()
        wf.status = WF_RUNNING
        wf.current_agent_key = agent_key
        wf.error_message = None
        wf.updated_at = _utcnow()
        self.db.commit()

        self.audit.log(
            action_type="workflow.rerun_agent",
            entity_type="ai_agent_run",
            entity_id=str(target.id),
            user_id=user_id,
            workflow_run_id=wf.id,
            agent_run_id=target.id,
            new_value={"agent_key": agent_key},
        )

        ar = self.execution.run_agent_row(target, agent_key=agent_key, context=context or {}, force=True)
        self.db.refresh(ar)
        if ar.status == AR_FAILED:
            wf.status = WF_FAILED
            wf.error_message = "فشل إعادة تشغيل الوكيل"
            wf.completed_at = _utcnow()
        elif ar.status == AR_WARNING:
            wf.status = WF_COMPLETED_WITH_WARNINGS
            wf.completed_at = _utcnow()
            wf.progress_percent = 100
        else:
            # تحقق إن كل الوكلاء ناجحون
            all_ok = all(
                r.status in (AR_SUCCESS, AR_WARNING) for r in self.agent_runs_for(wf.id)
            )
            warn = any(r.status == AR_WARNING for r in self.agent_runs_for(wf.id))
            if all_ok:
                wf.status = WF_COMPLETED_WITH_WARNINGS if warn else WF_COMPLETED
                wf.progress_percent = 100
                wf.completed_at = _utcnow()
                wf.current_agent_key = None
        wf.updated_at = _utcnow()
        self.db.commit()
        return wf

    def run_system_health(
        self,
        *,
        user_id: int | None = None,
        context: dict[str, Any] | None = None,
    ) -> AiWorkflowRun:
        if not ag_config.is_agentic_runtime_allowed():
            raise AgenticDisabledError()
        # تأكد من التسجيل
        if not self.registry.get_agent(SYSTEM_HEALTH_AGENT_KEY):
            from app.ai_agentic.migration import seed_system_health_defaults

            seed_system_health_defaults(self.db)

        settings = self.gateway.legacy_service.get_settings()
        wf = self.create_workflow_run(
            workflow_key=SYSTEM_HEALTH_WORKFLOW_KEY,
            workflow_name="System Health Check",
            agent_keys=[SYSTEM_HEALTH_AGENT_KEY],
            source_type="ai_center",
            source_id="system_health",
            user_id=user_id,
            model_name=settings.model_name,
            metadata={"purpose": "foundation_health"},
        )
        return self.start_workflow(run_id=wf.id, context=context or {}, user_id=user_id)

    def workflow_to_dict(self, wf: AiWorkflowRun) -> dict[str, Any]:
        from app.ai_agentic.display import agent_display_name_ar
        from app.ai_agentic.formatters import format_duration_ms
        from app.ai_agentic.models import AiAgent

        duration_ms = None
        if wf.started_at and wf.completed_at:
            duration_ms = int((wf.completed_at - wf.started_at).total_seconds() * 1000)
        elif wf.started_at:
            duration_ms = int((_utcnow() - wf.started_at).total_seconds() * 1000)
        agent_runs = []
        for ar in self.agent_runs_for(wf.id):
            ag = self.db.get(AiAgent, ar.agent_id) if ar.agent_id else None
            agent_key = ag.agent_key if ag else None
            out = loads_json(ar.output_json, default={}) or {}
            data = out.get("data") if isinstance(out, dict) else {}
            meta = out.get("metadata") if isinstance(out, dict) else {}
            agent_runs.append(
                {
                    "id": ar.id,
                    "agent_id": ar.agent_id,
                    "agent_key": agent_key,
                    "agent_name": agent_display_name_ar(agent_key or "", ag.display_name if ag else None),
                    "sequence_number": ar.sequence_number,
                    "status": ar.status,
                    "attempt_number": ar.attempt_number,
                    "duration_ms": ar.duration_ms,
                    "duration_display": format_duration_ms(ar.duration_ms),
                    "model_name": ar.model_name,
                    "prompt_version": ar.prompt_version,
                    "knowledge_version": ar.knowledge_version,
                    "started_at": ar.started_at.isoformat(sep=" ", timespec="seconds") if ar.started_at else None,
                    "completed_at": ar.completed_at.isoformat(sep=" ", timespec="seconds")
                    if ar.completed_at
                    else None,
                    "error": loads_json(ar.error_json),
                    "warnings": loads_json(ar.warning_json),
                    "input_summary": _summarize_json(loads_json(ar.input_json)),
                    "output_summary": _summarize_output(data, meta, out),
                    "output": out if isinstance(out, dict) else {},
                }
            )
        return {
            "id": wf.id,
            "workflow_key": wf.workflow_key,
            "workflow_name": wf.workflow_name,
            "source_type": wf.source_type,
            "source_id": wf.source_id,
            "requested_by_user_id": wf.requested_by_user_id,
            "status": wf.status,
            "current_agent_key": wf.current_agent_key,
            "progress_percent": wf.progress_percent,
            "started_at": wf.started_at.isoformat(sep=" ", timespec="seconds") if wf.started_at else None,
            "completed_at": wf.completed_at.isoformat(sep=" ", timespec="seconds") if wf.completed_at else None,
            "cancelled_at": wf.cancelled_at.isoformat(sep=" ", timespec="seconds") if wf.cancelled_at else None,
            "error_message": wf.error_message,
            "model_name": wf.model_name,
            "prompt_version": wf.prompt_version,
            "knowledge_version": wf.knowledge_version,
            "duration_ms": duration_ms,
            "duration_display": format_duration_ms(duration_ms),
            "metadata": loads_json(wf.metadata_json, default={}),
            "agent_runs": agent_runs,
            "created_at": wf.created_at.isoformat(sep=" ", timespec="seconds") if wf.created_at else None,
        }

    def get_workflow_details(self, run_id: int) -> dict[str, Any]:
        """تفاصيل كاملة: workflow + agent_runs + audit + system_events."""
        from app.ai_agentic.models import AiAuditLog, AiSystemEvent

        wf = self.get_workflow(run_id)
        workflow = self.workflow_to_dict(wf)
        audits = (
            self.db.query(AiAuditLog)
            .filter(AiAuditLog.workflow_run_id == wf.id)
            .order_by(AiAuditLog.created_at.asc(), AiAuditLog.id.asc())
            .all()
        )
        events = (
            self.db.query(AiSystemEvent)
            .filter(AiSystemEvent.workflow_run_id == wf.id)
            .order_by(AiSystemEvent.created_at.asc(), AiSystemEvent.id.asc())
            .all()
        )
        return {
            "ok": True,
            "success": True,
            "workflow": workflow,
            "agent_runs": workflow.get("agent_runs") or [],
            "audit_logs": [
                {
                    "id": r.id,
                    "user_id": r.user_id,
                    "action_type": r.action_type,
                    "entity_type": r.entity_type,
                    "entity_id": r.entity_id,
                    "workflow_run_id": r.workflow_run_id,
                    "agent_run_id": r.agent_run_id,
                    "old_value": loads_json(r.old_value_json),
                    "new_value": loads_json(r.new_value_json),
                    "created_at": r.created_at.isoformat(sep=" ", timespec="seconds") if r.created_at else None,
                }
                for r in audits
            ],
            "system_events": [
                {
                    "id": r.id,
                    "event_type": r.event_type,
                    "severity": r.severity,
                    "component": r.component,
                    "message": r.message,
                    "details": loads_json(r.details_json),
                    "created_at": r.created_at.isoformat(sep=" ", timespec="seconds") if r.created_at else None,
                }
                for r in events
            ],
        }


def _summarize_json(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, dict):
        keys = ", ".join(list(value.keys())[:8])
        return f"مفاتيح: {keys}" if keys else "{}"
    if isinstance(value, list):
        return f"قائمة ({len(value)})"
    s = str(value)
    return s[:120] + ("…" if len(s) > 120 else "")


def _summarize_output(data: Any, meta: Any, out: Any) -> str:
    if isinstance(data, dict) and data:
        status = data.get("status")
        model = data.get("model") or (meta.get("model") if isinstance(meta, dict) else None)
        parts = []
        if status:
            parts.append(f"status={status}")
        if model:
            parts.append(f"model={model}")
        if isinstance(meta, dict) and meta.get("duration_ms") is not None:
            parts.append(f"ms={meta.get('duration_ms')}")
        if parts:
            return " · ".join(parts)
    if isinstance(out, dict) and out.get("status"):
        return f"agent_status={out.get('status')}"
    return "—"
