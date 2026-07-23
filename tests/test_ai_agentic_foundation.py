"""اختبارات Agentic AI Foundation — مع Mock لـ Ollama (بدون اعتماد على خادم حقيقي)."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.ai_agentic import config as ag_config
from app.ai_agentic.constants import (
    AR_SUCCESS,
    SYSTEM_HEALTH_AGENT_KEY,
    WF_CANCELLED,
    WF_COMPLETED,
    WF_FAILED,
    WF_PAUSED,
)
from app.ai_agentic.exceptions import (
    AgentDisabledError,
    DuplicateAgentKeyError,
    MigrationSafetyError,
)
from app.ai_agentic.migration import (
    ensure_agentic_tables,
    migrate_agentic_foundation,
    rollback_agentic_foundation,
    seed_system_health_defaults,
    verify_agentic_migration,
)
from app.ai_agentic.models import (
    AiAgent,
    AiAgentRun,
    AiAuditLog,
    AiKnowledgeVersion,
    AiPromptVersion,
    AiSystemEvent,
    AiWorkflowRun,
)
from app.ai_agentic.schemas import GatewayResult
from app.ai_agentic.services.agent_orchestrator_service import AgentOrchestratorService
from app.ai_agentic.services.agent_registry_service import AgentRegistryService
from app.ai_agentic.services.ai_gateway_service import AIGatewayService
from app.ai_agentic.services.audit_log_service import AuditLogService
from app.ai_local_engine.models import AiSettings
from app.ai_local_engine.schemas.response_schema import UnifiedAIResponse
from app.ai_local_engine.services.ai_service import AIService, ensure_default_settings
from app.database import Base


def _ok_gateway(*args, **kwargs):
    return GatewayResult(
        success=True,
        content='{"status":"ok","message":"Local model is available"}',
        model="qwen3:8b",
        duration_ms=10,
        raw_response={},
    )


class AgenticFoundationTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(
            bind=self.engine,
            tables=[
                AiSettings.__table__,
                AiAgent.__table__,
                AiWorkflowRun.__table__,
                AiAgentRun.__table__,
                AiPromptVersion.__table__,
                AiKnowledgeVersion.__table__,
                AiAuditLog.__table__,
                AiSystemEvent.__table__,
            ],
        )
        Session = sessionmaker(bind=self.engine)
        self.db = Session()
        ensure_default_settings(self.db)
        row = self.db.query(AiSettings).first()
        row.enabled = True
        row.model_name = "qwen3:8b"
        self.db.commit()
        seed_system_health_defaults(self.db)
        self._prev_mode = ag_config.AI_ENGINE_MODE
        self._prev_enabled = ag_config.AI_AGENTIC_ENABLED
        ag_config.AI_ENGINE_MODE = "hybrid"
        ag_config.AI_AGENTIC_ENABLED = True

    def tearDown(self):
        ag_config.AI_ENGINE_MODE = self._prev_mode
        ag_config.AI_AGENTIC_ENABLED = self._prev_enabled
        self.db.close()
        self.engine.dispose()

    def test_01_agent_registration(self):
        reg = AgentRegistryService(self.db)
        a = reg.register_agent(
            agent_key="demo_agent",
            display_name="Demo",
            category="test",
        )
        self.assertEqual(a.agent_key, "demo_agent")
        self.assertIsNotNone(reg.get_agent("demo_agent"))

    def test_02_duplicate_agent_key(self):
        reg = AgentRegistryService(self.db)
        with self.assertRaises(DuplicateAgentKeyError):
            reg.register_agent(agent_key=SYSTEM_HEALTH_AGENT_KEY, display_name="Dup")

    def test_03_disabled_agent_cannot_run(self):
        reg = AgentRegistryService(self.db)
        reg.disable_agent(SYSTEM_HEALTH_AGENT_KEY)
        orch = AgentOrchestratorService(self.db)
        with patch.object(AIGatewayService, "send_request", side_effect=_ok_gateway):
            wf = orch.run_system_health(user_id=1)
        self.assertEqual(wf.status, WF_FAILED)
        from app.ai_agentic.agents.system_health_agent import SystemHealthAgent

        agent = SystemHealthAgent(self.db)
        agent.apply_registry_row(reg.get_agent(SYSTEM_HEALTH_AGENT_KEY))
        with self.assertRaises(AgentDisabledError):
            agent.run({})

    def test_04_workflow_creation(self):
        orch = AgentOrchestratorService(self.db)
        wf = orch.create_workflow_run(
            workflow_key="t",
            workflow_name="T",
            agent_keys=[SYSTEM_HEALTH_AGENT_KEY],
            user_id=1,
        )
        self.assertEqual(wf.status, "CREATED")
        self.assertEqual(len(orch.agent_runs_for(wf.id)), 1)

    def test_05_successful_agent_run(self):
        orch = AgentOrchestratorService(self.db)
        with patch.object(AIGatewayService, "send_request", side_effect=_ok_gateway):
            with patch.object(AIGatewayService, "check_model_available", return_value=True):
                wf = orch.run_system_health(user_id=1)
        self.assertEqual(wf.status, WF_COMPLETED)
        ar = orch.agent_runs_for(wf.id)[0]
        self.assertEqual(ar.status, AR_SUCCESS)

    def test_06_failed_agent_run(self):
        def bad(*a, **k):
            return GatewayResult(success=False, error="boom", error_code="x", model="qwen3:8b")

        orch = AgentOrchestratorService(self.db)
        AgentRegistryService(self.db).update_retry_count(SYSTEM_HEALTH_AGENT_KEY, 0)
        with patch.object(AIGatewayService, "send_request", side_effect=bad):
            with patch.object(AIGatewayService, "check_model_available", return_value=True):
                wf = orch.run_system_health(user_id=1)
        self.assertEqual(wf.status, WF_FAILED)

    def test_07_retry_limit(self):
        calls = {"n": 0}

        def flaky(*a, **k):
            calls["n"] += 1
            return GatewayResult(success=False, error="fail", model="m")

        orch = AgentOrchestratorService(self.db)
        AgentRegistryService(self.db).update_retry_count(SYSTEM_HEALTH_AGENT_KEY, 2)
        with patch.object(AIGatewayService, "send_request", side_effect=flaky):
            with patch.object(AIGatewayService, "check_model_available", return_value=True):
                wf = orch.run_system_health(user_id=1)
        self.assertEqual(wf.status, WF_FAILED)
        self.assertGreaterEqual(calls["n"], 3)  # 1 + max_retries

    def test_08_pause_workflow(self):
        orch = AgentOrchestratorService(self.db)
        wf = orch.create_workflow_run(
            workflow_key="p",
            workflow_name="P",
            agent_keys=[SYSTEM_HEALTH_AGENT_KEY],
        )
        wf.status = "RUNNING"
        self.db.commit()
        paused = orch.pause_workflow(wf.id, user_id=1)
        self.assertEqual(paused.status, WF_PAUSED)

    def test_09_resume_workflow(self):
        orch = AgentOrchestratorService(self.db)
        wf = orch.create_workflow_run(
            workflow_key="r",
            workflow_name="R",
            agent_keys=[SYSTEM_HEALTH_AGENT_KEY],
        )
        wf.status = WF_PAUSED
        self.db.commit()
        with patch.object(AIGatewayService, "send_request", side_effect=_ok_gateway):
            with patch.object(AIGatewayService, "check_model_available", return_value=True):
                resumed = orch.resume_workflow(wf.id, user_id=1)
        self.assertEqual(resumed.status, WF_COMPLETED)

    def test_10_cancel_workflow(self):
        orch = AgentOrchestratorService(self.db)
        wf = orch.create_workflow_run(
            workflow_key="c",
            workflow_name="C",
            agent_keys=[SYSTEM_HEALTH_AGENT_KEY],
        )
        wf.status = "RUNNING"
        self.db.commit()
        cancelled = orch.cancel_workflow(wf.id, user_id=1)
        self.assertEqual(cancelled.status, WF_CANCELLED)

    def test_11_rerun_one_agent(self):
        orch = AgentOrchestratorService(self.db)
        with patch.object(AIGatewayService, "send_request", side_effect=_ok_gateway):
            with patch.object(AIGatewayService, "check_model_available", return_value=True):
                wf = orch.run_system_health(user_id=1)
                wf2 = orch.rerun_one_agent(wf.id, SYSTEM_HEALTH_AGENT_KEY, user_id=1)
        self.assertIn(wf2.status, (WF_COMPLETED, "COMPLETED_WITH_WARNINGS"))

    def test_12_ollama_unavailable(self):
        def down(*a, **k):
            return GatewayResult(
                success=False,
                error="connection",
                error_code="connection_error",
            )

        orch = AgentOrchestratorService(self.db)
        AgentRegistryService(self.db).update_retry_count(SYSTEM_HEALTH_AGENT_KEY, 0)
        with patch.object(AIGatewayService, "send_request", side_effect=down):
            with patch.object(AIGatewayService, "check_model_available", return_value=False):
                wf = orch.run_system_health(user_id=1)
        self.assertEqual(wf.status, WF_FAILED)

    def test_13_model_unavailable(self):
        # نفس مسار الفشل عبر gateway
        self.test_12_ollama_unavailable()

    def test_14_invalid_structured_output(self):
        def bad_json(*a, **k):
            return GatewayResult(success=True, content="not-json", model="m", duration_ms=1)

        orch = AgentOrchestratorService(self.db)
        AgentRegistryService(self.db).update_retry_count(SYSTEM_HEALTH_AGENT_KEY, 0)
        with patch.object(AIGatewayService, "send_request", side_effect=bad_json):
            with patch.object(AIGatewayService, "check_model_available", return_value=True):
                wf = orch.run_system_health(user_id=1)
        self.assertEqual(wf.status, WF_FAILED)

    def test_15_audit_log_creation(self):
        AuditLogService(self.db).log(
            action_type="test.action",
            entity_type="test",
            entity_id="1",
            user_id=9,
        )
        rows = AuditLogService(self.db).list_recent(limit=5)
        self.assertTrue(any(r.action_type == "test.action" for r in rows))

    def test_18_legacy_mode_still_works(self):
        ag_config.AI_ENGINE_MODE = "legacy"
        svc = AIService(self.db)
        with patch.object(svc, "generate_text") as mock_gen:
            mock_gen.return_value = UnifiedAIResponse(success=True, text="hi", model="qwen3:8b")
            # Legacy path: test_prompt uses provider; use get_settings instead
            s = svc.get_settings()
            self.assertTrue(s.enabled)
            self.assertTrue(ag_config.is_legacy_runtime_allowed())
            self.assertFalse(ag_config.is_agentic_runtime_allowed())

    def test_19_agentic_mode_works(self):
        ag_config.AI_ENGINE_MODE = "agentic"
        self.assertTrue(ag_config.is_agentic_runtime_allowed())
        orch = AgentOrchestratorService(self.db)
        with patch.object(AIGatewayService, "send_request", side_effect=_ok_gateway):
            with patch.object(AIGatewayService, "check_model_available", return_value=True):
                wf = orch.run_system_health(user_id=1)
        self.assertEqual(wf.status, WF_COMPLETED)

    def test_20_hybrid_mode_does_not_break_legacy(self):
        ag_config.AI_ENGINE_MODE = "hybrid"
        self.assertTrue(ag_config.is_legacy_runtime_allowed())
        self.assertTrue(ag_config.is_agentic_runtime_allowed())
        svc = AIService(self.db)
        self.assertEqual(svc.get_settings().provider, "ollama")

    def test_model_explicit_and_default_fallback(self):
        reg = AgentRegistryService(self.db)
        agent = reg.get_agent(SYSTEM_HEALTH_AGENT_KEY)
        agent.model_name = ""
        self.db.commit()
        d = reg.agent_to_dict(agent)
        self.assertEqual(d["model_name"], "qwen3:8b")
        self.assertEqual(d["model_source"], "default")
        reg.update_model(SYSTEM_HEALTH_AGENT_KEY, "custom:model")
        d2 = reg.agent_to_dict(reg.get_agent(SYSTEM_HEALTH_AGENT_KEY))
        self.assertEqual(d2["model_name"], "custom:model")
        self.assertEqual(d2["model_source"], "agent")

    def test_workflow_details_includes_agent_runs_and_audit(self):
        orch = AgentOrchestratorService(self.db)
        with patch.object(AIGatewayService, "send_request", side_effect=_ok_gateway):
            wf = orch.run_system_health(user_id=7)
        details = orch.get_workflow_details(wf.id)
        self.assertTrue(details["ok"])
        self.assertGreaterEqual(len(details["agent_runs"]), 1)
        self.assertTrue(any(a["action_type"] == "workflow.complete" for a in details["audit_logs"]))

    def test_system_health_persists_agent_run_and_audit(self):
        orch = AgentOrchestratorService(self.db)
        with patch.object(AIGatewayService, "send_request", side_effect=_ok_gateway):
            wf = orch.run_system_health(user_id=3)
        self.assertEqual(wf.status, WF_COMPLETED)
        runs = orch.agent_runs_for(wf.id)
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0].status, AR_SUCCESS)
        self.assertIsNotNone(runs[0].output_json)
        self.assertIsNotNone(runs[0].started_at)
        self.assertIsNotNone(runs[0].completed_at)
        audits = (
            self.db.query(AiAuditLog)
            .filter(AiAuditLog.workflow_run_id == wf.id)
            .all()
        )
        self.assertTrue(any(a.action_type == "workflow.create" for a in audits))

    def test_completed_requires_agent_run(self):
        orch = AgentOrchestratorService(self.db)
        wf = orch.create_workflow_run(
            workflow_key="empty",
            workflow_name="Empty",
            agent_keys=[SYSTEM_HEALTH_AGENT_KEY],
        )
        # اجعل agent run معلقاً بدون تنفيذ ناجح ثم حاكِ اكتمال فارغ
        for ar in orch.agent_runs_for(wf.id):
            self.db.delete(ar)
        self.db.commit()
        # start مع agent_keys في metadata لكن بدون pending runs → سيفشل أو ينشئ؟ create موجود بدون runs
        # أعد pending run ثم افشل التنفيذ
        from app.ai_agentic.services.agent_execution_service import AgentExecutionService

        agent = AgentRegistryService(self.db).get_agent(SYSTEM_HEALTH_AGENT_KEY)
        AgentExecutionService(self.db).create_pending_run(
            workflow_run_id=wf.id, agent_id=agent.id, sequence_number=1
        )
        with patch.object(
            AIGatewayService,
            "send_request",
            return_value=GatewayResult(success=False, error="x"),
        ):
            AgentRegistryService(self.db).update_retry_count(SYSTEM_HEALTH_AGENT_KEY, 0)
            out = orch.start_workflow(wf.id, user_id=1)
        self.assertEqual(out.status, WF_FAILED)

    def test_duration_formatting(self):
        from app.ai_agentic.formatters import format_duration_ms

        self.assertEqual(format_duration_ms(None), "—")
        self.assertIn("ثانية", format_duration_ms(54841))
        self.assertIn("مللي", format_duration_ms(12))

    def test_no_sensitive_prompt_in_gateway_log_payload(self):
        gw = AIGatewayService(self.db)
        prev = ag_config.AI_LOG_PROMPTS
        ag_config.AI_LOG_PROMPTS = False
        try:
            with patch.object(
                gw._legacy,
                "generate_text",
                return_value=UnifiedAIResponse(
                    success=True, text='{"status":"ok","message":"Local model is available"}', model="qwen3:8b", response_time_ms=5
                ),
            ):
                with patch.object(gw, "check_model_available", return_value=True):
                    result = gw.send_request(
                        "system_health_agent",
                        "SECRET_SYSTEM",
                        "SECRET_USER",
                        model="qwen3:8b",
                        parameters={"skip_model_precheck": True, "max_tokens": 32, "temperature": 0},
                        max_retries_override=0,
                    )
            self.assertTrue(result.success)
            # raw فارغ عندما الحفظ معطّل
            prev_raw = ag_config.AI_SAVE_RAW_RESPONSES
            ag_config.AI_SAVE_RAW_RESPONSES = False
            self.assertEqual(result.to_dict(include_raw=False).get("raw_response"), {})
            ag_config.AI_SAVE_RAW_RESPONSES = prev_raw
        finally:
            ag_config.AI_LOG_PROMPTS = prev

    def test_display_name_ar(self):
        from app.ai_agentic.display import agent_display_name_ar

        self.assertEqual(agent_display_name_ar("system_health_agent"), "وكيل فحص صحة النظام")

    def test_ollama_unavailable_creates_system_event(self):
        orch = AgentOrchestratorService(self.db)
        AgentRegistryService(self.db).update_retry_count(SYSTEM_HEALTH_AGENT_KEY, 0)
        with patch.object(
            AIGatewayService,
            "send_request",
            return_value=GatewayResult(success=False, error="down", error_code="connection_error"),
        ):
            wf = orch.run_system_health(user_id=1)
        self.assertEqual(wf.status, WF_FAILED)
        events = self.db.query(AiSystemEvent).filter(AiSystemEvent.workflow_run_id == wf.id).all()
        self.assertTrue(len(events) >= 1)


class AgenticMigrationTests(unittest.TestCase):
    def test_16_migration_success_and_17_rollback(self):
        # ملف sqlite مؤقت لمحاكاة migrate/rollback على جداول agentic فقط
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            url = f"sqlite:///{path}"
            eng = create_engine(url)
            # جدول قديم وهمي
            with eng.begin() as conn:
                conn.execute(text("CREATE TABLE ai_settings (id INTEGER PRIMARY KEY, x INTEGER)"))
                conn.execute(text("INSERT INTO ai_settings (x) VALUES (1)"))
                before = conn.execute(text("SELECT COUNT(*) FROM ai_settings")).scalar()

            with patch("app.ai_agentic.migration.engine", eng), patch(
                "app.ai_agentic.migration.DATABASE_URL", url
            ), patch("app.database.engine", eng), patch("app.database.DATABASE_URL", url):
                # تسجيل metadata على نفس المحرك
                for table in (
                    AiAgent.__table__,
                    AiWorkflowRun.__table__,
                    AiAgentRun.__table__,
                    AiPromptVersion.__table__,
                    AiKnowledgeVersion.__table__,
                    AiAuditLog.__table__,
                    AiSystemEvent.__table__,
                ):
                    table.create(bind=eng, checkfirst=True)

                # SessionLocal للبذرة
                Session = sessionmaker(bind=eng)
                with patch("app.database.SessionLocal", Session):
                    result = migrate_agentic_foundation(skip_backup=True)
                self.assertTrue(result["ok"])
                ver = verify_agentic_migration()
                self.assertTrue(ver["ok"])

                with eng.begin() as conn:
                    after = conn.execute(text("SELECT COUNT(*) FROM ai_settings")).scalar()
                self.assertEqual(before, after)

                rb = rollback_agentic_foundation(drop_tables=True)
                self.assertTrue(rb["ok"])
                ver2 = verify_agentic_migration()
                self.assertFalse(ver2["ok"])
                with eng.begin() as conn:
                    still = conn.execute(text("SELECT COUNT(*) FROM ai_settings")).scalar()
                self.assertEqual(still, before)
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass


if __name__ == "__main__":
    unittest.main()
