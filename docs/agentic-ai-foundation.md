# Agentic AI Foundation (PHASE A)

## Architecture Overview

The application keeps the **Legacy Local AI Engine** (`app/ai_local_engine`) and adds a parallel **Agentic AI Engine** (`app/ai_agentic`).

```
Application
    |
    +-- Legacy AI Engine (AIService / OllamaProvider)
    |
    +-- Agentic AI Engine
            |
            +-- Agent Orchestrator
            |
            +-- Agent Registry
            |
            +-- AI Gateway  (wraps AIService — sole Ollama access)
            |
            +-- Agent Run Store
            |
            +-- Audit Log
            |
            +-- Prompt Versions
            |
            +-- Knowledge Versions
```

Agents **must not** call Ollama directly. All model calls go through `AIGatewayService.send_request(...)`, which delegates to `AIService.generate_text`.

## Components

| Component | Module |
|-----------|--------|
| AI Gateway | `app/ai_agentic/services/ai_gateway_service.py` (+ `AIService.send_request`) |
| Agent Registry | `app/ai_agentic/services/agent_registry_service.py` |
| Orchestrator | `app/ai_agentic/services/agent_orchestrator_service.py` |
| Execution | `app/ai_agentic/services/agent_execution_service.py` |
| BaseAgent | `app/ai_agentic/agents/base_agent.py` |
| System Health Agent | `app/ai_agentic/agents/system_health_agent.py` |
| Audit / System events | `app/ai_agentic/services/audit_log_service.py` |
| Migration | `app/ai_agentic/migration.py` + `scripts/migrate_agentic_foundation.py` |

## Database Tables

- `ai_agents`
- `ai_workflow_runs`
- `ai_agent_runs`
- `ai_prompt_versions`
- `ai_knowledge_versions`
- `ai_audit_logs`
- `ai_system_events`

JSON payloads are stored as SQLite `TEXT` via `json_util.dumps_json` / `loads_json`.

## Workflow States

`CREATED` → `QUEUED` → `RUNNING` → (`PAUSED`) → `COMPLETED` | `COMPLETED_WITH_WARNINGS` | `FAILED` | `CANCELLED`

## Agent States

`PENDING` | `RUNNING` | `RETRYING` | `SUCCESS` | `WARNING` | `FAILED` | `SKIPPED` | `CANCELLED`

## Engine Mode Switch

Environment / config:

| Variable | Default | Meaning |
|----------|---------|---------|
| `AI_ENGINE_MODE` | `hybrid` | `legacy` / `agentic` / `hybrid` |
| `AI_AGENTIC_ENABLED` | `true` | Master switch for agentic runtime |
| `AI_DEFAULT_MODEL` | (from legacy) | Default model name |
| `AI_DEFAULT_TIMEOUT` | `120` | Default agent timeout (seconds) |
| `AI_DEFAULT_MAX_RETRIES` | `2` | Default retries |
| `AI_SAVE_RAW_RESPONSES` | `false` | Persist raw provider payload |
| `AI_LOG_PROMPTS` | `false` | Log full prompt text |

- **legacy**: only Legacy engine APIs/UI paths are intended for production AI calls; agentic runtime is blocked.
- **agentic**: agentic workflows allowed.
- **hybrid** (default): both allowed; existing Prompt Testing / Report Library keep using Legacy `AIService`.

## How to Register a New Agent

1. Implement a class inheriting `BaseAgent` under `app/ai_agentic/agents/`.
2. Register the class in `app/ai_agentic/agents/__init__.py` (`_CODE_AGENTS`).
3. Insert a row via `AgentRegistryService.register_agent(...)` (unique `agent_key`).
4. Optionally add an `ai_prompt_versions` row and link `prompt_version_id`.

Do **not** create Training Agents in PHASE A.

## How to Run System Health Agent

**UI:** AI Center → Agentic AI Management → «تشغيل System Health Test»

**API:**

```http
POST /api/ai/system-health/run
```

Requires AI Center authentication (system admin).

## How to Enable or Disable Agentic Mode

Set `AI_ENGINE_MODE=legacy` to disable agentic runtime, or `AI_AGENTIC_ENABLED=false`.

Restart the app after changing environment variables.

## Migration Steps

```bat
.venv\Scripts\python.exe scripts\migrate_agentic_foundation.py backup-db
.venv\Scripts\python.exe scripts\migrate_agentic_foundation.py migrate-agentic-foundation
.venv\Scripts\python.exe scripts\migrate_agentic_foundation.py verify-agentic-migration
```

App startup also calls `ensure_ai_agentic_foundation_tables()` (create + seed) safely.

## Rollback Steps

Restore a backup file:

```bat
.venv\Scripts\python.exe scripts\migrate_agentic_foundation.py rollback-agentic-foundation --restore-from backups\exercises_pre_agentic_YYYYMMDD_HHMMSS.db
```

Or drop agentic tables only (legacy data untouched):

```bat
.venv\Scripts\python.exe scripts\migrate_agentic_foundation.py rollback-agentic-foundation --drop-tables-only
```

## Troubleshooting

| Symptom | Check |
|---------|--------|
| AgenticDisabledError | `AI_ENGINE_MODE`, `AI_AGENTIC_ENABLED` |
| Ollama connection errors | Legacy AI Center connection test; Gateway logs |
| Invalid structured output | Model reply must be JSON with `status=ok` |
| Duplicate agent_key | Registry enforces uniqueness |
| Pause does nothing mid-call | Pause applies between agents (sync runner) |

## Security Notes

- Offline / local only; no cloud APIs in the agentic path.
- Agents never import `OllamaProvider`.
- Prompts/raw responses are not stored unless flags are enabled.
- Audit logs record who changed agents/workflows; no passwords/tokens.
- Permissions: `can_ai_*` (system admin), separate from analyst evaluation modules.

## Future Integration Points

- Training Agents (report analysis) — later phase
- Final report generator button — later phase
- Multi-agent pipelines A→B→C (orchestrator already accepts `agent_keys` list)
- Wire evaluation lists / scores / AAR — **explicitly out of scope** for PHASE A

## API Endpoints (AI Center)

| Method | Path |
|--------|------|
| GET | `/api/ai/agents` |
| GET | `/api/ai/agents/<agent_key>` |
| POST | `/api/ai/agents/<agent_key>/enable` |
| POST | `/api/ai/agents/<agent_key>/disable` |
| GET | `/api/ai/workflows` |
| GET | `/api/ai/workflows/<run_id>` |
| POST | `/api/ai/workflows/<run_id>/pause` |
| POST | `/api/ai/workflows/<run_id>/resume` |
| POST | `/api/ai/workflows/<run_id>/cancel` |
| POST | `/api/ai/workflows/<run_id>/retry` |
| POST | `/api/ai/workflows/<run_id>/agents/<agent_key>/rerun` |
| POST | `/api/ai/system-health/run` |
| GET | `/api/ai/system-events` |
| GET | `/api/ai/audit-logs` |
| GET | `/api/ai/engine-mode` |

UI page: `/ai-center/agentic`
