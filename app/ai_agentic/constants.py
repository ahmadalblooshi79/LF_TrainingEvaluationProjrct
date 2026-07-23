"""ثوابت الحالات والمفاتيح."""

from __future__ import annotations

# Workflow run statuses
WF_CREATED = "CREATED"
WF_QUEUED = "QUEUED"
WF_RUNNING = "RUNNING"
WF_PAUSED = "PAUSED"
WF_COMPLETED = "COMPLETED"
WF_COMPLETED_WITH_WARNINGS = "COMPLETED_WITH_WARNINGS"
WF_FAILED = "FAILED"
WF_CANCELLED = "CANCELLED"

WORKFLOW_STATUSES = frozenset(
    {
        WF_CREATED,
        WF_QUEUED,
        WF_RUNNING,
        WF_PAUSED,
        WF_COMPLETED,
        WF_COMPLETED_WITH_WARNINGS,
        WF_FAILED,
        WF_CANCELLED,
    }
)

# Agent run statuses
AR_PENDING = "PENDING"
AR_RUNNING = "RUNNING"
AR_SUCCESS = "SUCCESS"
AR_WARNING = "WARNING"
AR_FAILED = "FAILED"
AR_SKIPPED = "SKIPPED"
AR_RETRYING = "RETRYING"
AR_CANCELLED = "CANCELLED"

AGENT_RUN_STATUSES = frozenset(
    {
        AR_PENDING,
        AR_RUNNING,
        AR_SUCCESS,
        AR_WARNING,
        AR_FAILED,
        AR_SKIPPED,
        AR_RETRYING,
        AR_CANCELLED,
    }
)

SYSTEM_HEALTH_AGENT_KEY = "system_health_agent"
SYSTEM_HEALTH_WORKFLOW_KEY = "system_health_check"

KNOWLEDGE_STATUS_DRAFT = "draft"
KNOWLEDGE_STATUS_ACTIVE = "active"
KNOWLEDGE_STATUS_ARCHIVED = "archived"

AGENTIC_TABLES = (
    "ai_agents",
    "ai_workflow_runs",
    "ai_agent_runs",
    "ai_prompt_versions",
    "ai_knowledge_versions",
    "ai_audit_logs",
    "ai_system_events",
)
