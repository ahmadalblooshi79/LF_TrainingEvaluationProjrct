"""مسارات Agentic AI — تُسجَّل على blueprint views."""

from __future__ import annotations

from flask import g, jsonify, redirect, render_template, request

from app.ai_agentic import config as ag_config
from app.ai_agentic.exceptions import AgenticAIError
from app.ai_agentic.services.agent_orchestrator_service import AgentOrchestratorService
from app.ai_agentic.services.agent_registry_service import AgentRegistryService
from app.ai_agentic.services.ai_gateway_service import AIGatewayService
from app.ai_agentic.services.audit_log_service import AuditLogService, AiSystemEventService
from app.ai_local_engine.services.ai_service import AIService
from app.ai_local_engine.services.health_service import HealthService
from app.permissions import (
    can_access_ai_center,
    can_ai_agent_manage,
    can_ai_audit_view,
    can_ai_workflow_manage,
    can_ai_workflow_run,
)


def _json_error(exc: Exception, status: int = 400):
    if isinstance(exc, AgenticAIError):
        return jsonify(
            {"ok": False, "error": exc.error_code, "error_message": exc.user_message}
        ), status
    return jsonify(
        {"ok": False, "error": "server_error", "error_message": "تعذر إكمال الطلب."}
    ), 500


def _req_meta():
    return {
        "ip_address": (request.headers.get("X-Forwarded-For") or request.remote_addr or "")[:64],
        "user_agent": (request.headers.get("User-Agent") or "")[:512],
    }


def register_agentic_routes(bp, *, get_current_user_optional, abort, _ctx):
    """تسجيل مسارات الصفحة وواجهات JSON داخل AI Center فقط."""

    @bp.route("/ai-center/agentic")
    def ai_agentic_management():
        user = get_current_user_optional()
        if not user:
            return redirect("/login?next=/ai-center/agentic")
        if not can_access_ai_center(user):
            abort(403)

        orch = AgentOrchestratorService(g.db)
        registry = AgentRegistryService(g.db)
        events = AiSystemEventService(g.db)
        legacy = AIService(g.db)
        settings = legacy.get_settings()
        health = HealthService(g.db).check(probe_model=False)

        agents = [registry.agent_to_dict(a) for a in registry.list_agents()]
        workflows = [orch.workflow_to_dict(w) for w in orch.list_workflows(limit=30)]
        recent_errors = events.list_recent(limit=20, severity="error")
        if len(recent_errors) < 5:
            recent_errors = events.list_recent(limit=20)

        health_result = None
        if request.args.get("health_status"):
            health_result = {
                "status": request.args.get("health_status"),
                "model": request.args.get("health_model") or settings.model_name or "—",
                "duration": request.args.get("health_duration") or "—",
                "gateway_duration": request.args.get("health_gateway") or "—",
                "attempts": request.args.get("health_attempts") or "1",
                "warmup": request.args.get("health_warmup") or "0",
                "run_id": request.args.get("health_run_id") or "—",
                "ollama": "متصل" if health.server_reachable else "غير متصل",
            }

        return render_template(
            "ai_agentic_management.html",
            **_ctx(
                user,
                settings=settings,
                health=health,
                engine_mode=ag_config.AI_ENGINE_MODE,
                agentic_enabled=ag_config.AI_AGENTIC_ENABLED and ag_config.is_agentic_runtime_allowed(),
                agents=agents,
                workflows=workflows,
                recent_events=recent_errors,
                health_result=health_result,
                can_manage_agents=can_ai_agent_manage(user),
                can_run_workflows=can_ai_workflow_run(user),
                can_manage_workflows=can_ai_workflow_manage(user),
                can_view_audit=can_ai_audit_view(user),
                error=request.args.get("err"),
                ok_msg=request.args.get("ok"),
            ),
        )

    def _api_user(*, manage_agents=False, run_wf=False, manage_wf=False, audit=False):
        user = get_current_user_optional()
        if not user:
            return None, (
                jsonify({"ok": False, "error": "unauthorized", "error_message": "يلزم تسجيل الدخول."}),
                401,
            )
        if not can_access_ai_center(user):
            return None, (jsonify({"ok": False, "error": "forbidden", "error_message": "غير مصرح."}), 403)
        if manage_agents and not can_ai_agent_manage(user):
            return None, (jsonify({"ok": False, "error": "forbidden", "error_message": "غير مصرح بإدارة الوكلاء."}), 403)
        if run_wf and not can_ai_workflow_run(user):
            return None, (jsonify({"ok": False, "error": "forbidden", "error_message": "غير مصرح بتشغيل المسارات."}), 403)
        if manage_wf and not can_ai_workflow_manage(user):
            return None, (jsonify({"ok": False, "error": "forbidden", "error_message": "غير مصرح بإدارة المسارات."}), 403)
        if audit and not can_ai_audit_view(user):
            return None, (jsonify({"ok": False, "error": "forbidden", "error_message": "غير مصرح بعرض التدقيق."}), 403)
        return user, None

    @bp.route("/api/ai/agents", methods=["GET"])
    def api_ai_agents_list():
        user, err = _api_user()
        if err:
            return err
        registry = AgentRegistryService(g.db)
        return jsonify({"ok": True, "agents": [registry.agent_to_dict(a) for a in registry.list_agents()]})

    @bp.route("/api/ai/agents/<agent_key>", methods=["GET"])
    def api_ai_agent_get(agent_key: str):
        user, err = _api_user()
        if err:
            return err
        try:
            registry = AgentRegistryService(g.db)
            row = registry.get_agent_or_raise(agent_key)
            return jsonify({"ok": True, "agent": registry.agent_to_dict(row)})
        except AgenticAIError as exc:
            return _json_error(exc, 404)

    @bp.route("/api/ai/agents/<agent_key>/enable", methods=["POST"])
    def api_ai_agent_enable(agent_key: str):
        user, err = _api_user(manage_agents=True)
        if err:
            return err
        try:
            registry = AgentRegistryService(g.db)
            row = registry.enable_agent(agent_key, user_id=user.id)
            meta = _req_meta()
            AuditLogService(g.db).log(
                action_type="api.agent.enable",
                entity_type="ai_agent",
                entity_id=agent_key,
                user_id=user.id,
                new_value={"enabled": True},
                **meta,
            )
            return jsonify({"ok": True, "agent": registry.agent_to_dict(row)})
        except AgenticAIError as exc:
            return _json_error(exc, 400)

    @bp.route("/api/ai/agents/<agent_key>/disable", methods=["POST"])
    def api_ai_agent_disable(agent_key: str):
        user, err = _api_user(manage_agents=True)
        if err:
            return err
        try:
            registry = AgentRegistryService(g.db)
            row = registry.disable_agent(agent_key, user_id=user.id)
            meta = _req_meta()
            AuditLogService(g.db).log(
                action_type="api.agent.disable",
                entity_type="ai_agent",
                entity_id=agent_key,
                user_id=user.id,
                new_value={"enabled": False},
                **meta,
            )
            return jsonify({"ok": True, "agent": registry.agent_to_dict(row)})
        except AgenticAIError as exc:
            return _json_error(exc, 400)

    @bp.route("/api/ai/workflows", methods=["GET"])
    def api_ai_workflows_list():
        user, err = _api_user()
        if err:
            return err
        orch = AgentOrchestratorService(g.db)
        return jsonify(
            {"ok": True, "workflows": [orch.workflow_to_dict(w) for w in orch.list_workflows(limit=50)]}
        )

    @bp.route("/api/ai/workflows/<int:run_id>", methods=["GET"])
    def api_ai_workflow_get(run_id: int):
        user, err = _api_user()
        if err:
            return err
        try:
            orch = AgentOrchestratorService(g.db)
            return jsonify({"ok": True, "workflow": orch.workflow_to_dict(orch.get_workflow(run_id))})
        except AgenticAIError as exc:
            return _json_error(exc, 404)

    @bp.route("/api/ai/workflows/<int:run_id>/details", methods=["GET"])
    def api_ai_workflow_details(run_id: int):
        user, err = _api_user()
        if err:
            return err
        try:
            orch = AgentOrchestratorService(g.db)
            details = orch.get_workflow_details(run_id)
            # إخفاء audit التفصيلي إن لم توجد صلاحية — مع الإبقاء على agent_runs
            if not can_ai_audit_view(user):
                details["audit_logs"] = []
            return jsonify(details)
        except AgenticAIError as exc:
            return _json_error(exc, 404)

    @bp.route("/api/ai/workflows/<int:run_id>/pause", methods=["POST"])
    def api_ai_workflow_pause(run_id: int):
        user, err = _api_user(manage_wf=True)
        if err:
            return err
        try:
            orch = AgentOrchestratorService(g.db)
            wf = orch.pause_workflow(run_id, user_id=user.id)
            return jsonify({"ok": True, "workflow": orch.workflow_to_dict(wf)})
        except AgenticAIError as exc:
            return _json_error(exc, 400)

    @bp.route("/api/ai/workflows/<int:run_id>/resume", methods=["POST"])
    def api_ai_workflow_resume(run_id: int):
        user, err = _api_user(manage_wf=True)
        if err:
            return err
        try:
            orch = AgentOrchestratorService(g.db)
            wf = orch.resume_workflow(run_id, user_id=user.id)
            return jsonify({"ok": True, "workflow": orch.workflow_to_dict(wf)})
        except AgenticAIError as exc:
            return _json_error(exc, 400)

    @bp.route("/api/ai/workflows/<int:run_id>/cancel", methods=["POST"])
    def api_ai_workflow_cancel(run_id: int):
        user, err = _api_user(manage_wf=True)
        if err:
            return err
        try:
            orch = AgentOrchestratorService(g.db)
            wf = orch.cancel_workflow(run_id, user_id=user.id)
            return jsonify({"ok": True, "workflow": orch.workflow_to_dict(wf)})
        except AgenticAIError as exc:
            return _json_error(exc, 400)

    @bp.route("/api/ai/workflows/<int:run_id>/retry", methods=["POST"])
    def api_ai_workflow_retry(run_id: int):
        user, err = _api_user(manage_wf=True)
        if err:
            return err
        try:
            orch = AgentOrchestratorService(g.db)
            wf = orch.retry_workflow(run_id, user_id=user.id)
            return jsonify({"ok": True, "workflow": orch.workflow_to_dict(wf)})
        except AgenticAIError as exc:
            return _json_error(exc, 400)

    @bp.route("/api/ai/workflows/<int:run_id>/agents/<agent_key>/rerun", methods=["POST"])
    def api_ai_workflow_rerun_agent(run_id: int, agent_key: str):
        user, err = _api_user(manage_wf=True)
        if err:
            return err
        try:
            orch = AgentOrchestratorService(g.db)
            wf = orch.rerun_one_agent(run_id, agent_key, user_id=user.id)
            return jsonify({"ok": True, "workflow": orch.workflow_to_dict(wf)})
        except AgenticAIError as exc:
            return _json_error(exc, 400)

    @bp.route("/api/ai/system-health/run", methods=["POST"])
    def api_ai_system_health_run():
        user, err = _api_user(run_wf=True)
        if err:
            return err
        try:
            orch = AgentOrchestratorService(g.db)
            wf = orch.run_system_health(user_id=user.id)
            AuditLogService(g.db).log(
                action_type="api.system_health.run",
                entity_type="ai_workflow_run",
                entity_id=str(wf.id),
                user_id=user.id,
                workflow_run_id=wf.id,
                **_req_meta(),
            )
            return jsonify({"ok": True, "workflow": orch.workflow_to_dict(wf)})
        except AgenticAIError as exc:
            return _json_error(exc, 400)
        except Exception:
            return jsonify(
                {"ok": False, "error": "server_error", "error_message": "فشل اختبار صحة النظام."}
            ), 500

    @bp.route("/api/ai/system-events", methods=["GET"])
    def api_ai_system_events():
        user, err = _api_user()
        if err:
            return err
        limit = min(int(request.args.get("limit") or 50), 200)
        rows = AiSystemEventService(g.db).list_recent(limit=limit)
        return jsonify(
            {
                "ok": True,
                "events": [
                    {
                        "id": r.id,
                        "event_type": r.event_type,
                        "severity": r.severity,
                        "component": r.component,
                        "message": r.message,
                        "workflow_run_id": r.workflow_run_id,
                        "agent_run_id": r.agent_run_id,
                        "created_at": r.created_at.isoformat(sep=" ", timespec="seconds")
                        if r.created_at
                        else None,
                    }
                    for r in rows
                ],
            }
        )

    @bp.route("/api/ai/audit-logs", methods=["GET"])
    def api_ai_audit_logs():
        user, err = _api_user(audit=True)
        if err:
            return err
        limit = min(int(request.args.get("limit") or 50), 200)
        rows = AuditLogService(g.db).list_recent(limit=limit)
        return jsonify(
            {
                "ok": True,
                "audit_logs": [
                    {
                        "id": r.id,
                        "user_id": r.user_id,
                        "action_type": r.action_type,
                        "entity_type": r.entity_type,
                        "entity_id": r.entity_id,
                        "workflow_run_id": r.workflow_run_id,
                        "agent_run_id": r.agent_run_id,
                        "created_at": r.created_at.isoformat(sep=" ", timespec="seconds")
                        if r.created_at
                        else None,
                    }
                    for r in rows
                ],
            }
        )

    @bp.route("/api/ai/engine-mode", methods=["GET"])
    def api_ai_engine_mode():
        user, err = _api_user()
        if err:
            return err
        gw = AIGatewayService(g.db)
        settings = gw.legacy_service.get_settings()
        return jsonify(
            {
                "ok": True,
                "engine_mode": ag_config.AI_ENGINE_MODE,
                "agentic_enabled": ag_config.AI_AGENTIC_ENABLED,
                "agentic_runtime_allowed": ag_config.is_agentic_runtime_allowed(),
                "legacy_runtime_allowed": ag_config.is_legacy_runtime_allowed(),
                "model_name": settings.model_name,
                "legacy_enabled": settings.enabled,
            }
        )

    @bp.route("/ai-center/agentic/system-health", methods=["POST"])
    def ai_agentic_system_health_form():
        user = get_current_user_optional()
        if not user:
            return redirect("/login?next=/ai-center/agentic")
        if not can_ai_workflow_run(user):
            abort(403)
        from urllib.parse import quote

        from app.ai_agentic.formatters import format_duration_ms
        from app.ai_agentic.json_util import loads_json

        try:
            orch = AgentOrchestratorService(g.db)
            wf = orch.run_system_health(user_id=user.id)
            AuditLogService(g.db).log(
                action_type="api.system_health.run",
                entity_type="ai_workflow_run",
                entity_id=str(wf.id),
                user_id=user.id,
                workflow_run_id=wf.id,
                **_req_meta(),
            )
            runs = orch.agent_runs_for(wf.id)
            ar = runs[-1] if runs else None
            out = loads_json(ar.output_json, default={}) if ar else {}
            data = (out or {}).get("data") if isinstance(out, dict) else {}
            meta = (out or {}).get("metadata") if isinstance(out, dict) else {}
            gateway_ms = (data or {}).get("gateway_duration_ms") or (meta or {}).get("gateway_duration_ms") or (
                ar.duration_ms if ar else None
            )
            total_ms = (data or {}).get("total_duration_ms") or (meta or {}).get("duration_ms") or (
                ar.duration_ms if ar else None
            )
            attempts = (data or {}).get("retry_count")
            if attempts is None:
                attempts = (ar.attempt_number - 1) if ar else 0
            attempts = int(attempts) + 1
            warmup = "1" if (data or {}).get("model_warmup_detected") else "0"
            ok = wf.status in ("COMPLETED", "COMPLETED_WITH_WARNINGS")
            q = (
                f"health_status={'نجاح' if ok else 'فشل'}"
                f"&health_model={quote(str(wf.model_name or (ar.model_name if ar else '') or ''))}"
                f"&health_duration={quote(format_duration_ms(total_ms))}"
                f"&health_gateway={quote(format_duration_ms(gateway_ms))}"
                f"&health_attempts={attempts}"
                f"&health_warmup={warmup}"
                f"&health_run_id={wf.id}"
            )
            if ok:
                q += f"&ok={quote('اكتمل اختبار صحة النظام')}"
            else:
                q += f"&err={quote(wf.error_message or 'فشل اختبار صحة النظام')}"
            return redirect(f"/ai-center/agentic?{q}")
        except AgenticAIError as exc:
            return redirect(f"/ai-center/agentic?err={quote(exc.user_message)}")
        except Exception:
            return redirect("/ai-center/agentic?err=" + quote("فشل اختبار صحة النظام"))
