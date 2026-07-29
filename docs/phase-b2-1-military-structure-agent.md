# Phase B2.1 — Military Document Structure Agent

## Scope

إضافة **وكيل تحليل البنية العسكرية** كطبقة مستقلة بعد اعتماد جودة الاستخراج.

- يفهم الهيكل والترقيم والعلاقات Parent/Child فقط.
- **لا** يفسر المحتوى، ولا يعيد صياغة النص، ولا يعلّم النظام، ولا يغيّر Blocks أو اعتماد الاستخراج.
- **ليس** Phase B2.2 (Terminology / Units / Findings / Staff Duties / Institutional Memory).

## Architecture

```
Approved Extraction (B1)
        │
        ▼
Military Structure Workflow (military_structure_analysis)
        │
        ▼
Military Structure Agent (hybrid)
   ├─ Rule Engine (deterministic numbering + styles)
   ├─ Chunker (uncertain regions only → Qwen via AI Gateway)
   └─ Validator (technical, not an agent)
        │
        ▼
Structure tables (independent layer)
        │
        ▼
Structure Review UI → Approve Structure (lock run)
```

Word Review Mode (B1.5) يبقى كما هو مع Overlay اختياري عند وجود Structure Run.

## Agent behavior

| Key | Value |
|---|---|
| agent_key | `military_structure_agent` |
| workflow_key | `military_structure_analysis` |
| display_name_ar | وكيل تحليل البنية العسكرية للوثيقة |
| category | training |
| version | 1.0.0 |

Prerequisite: `APPROVED_EXTRACTION` (الافتراضي) أو `REVIEW_COMPLETED` مع صلاحية تحليل.

## Rule Engine

Patterns (configuration-driven in `numbering_rules.py`):

| Pattern | Style | Level |
|---|---|---|
| `1.` | arabic_dot | 1 |
| `أ.` | arabic_letter_dot | 2 |
| `(1)` | number_parentheses | 3 |
| `(أ)` | letter_parentheses | 4 |
| `1)` | number_close_paren | 5 |

Also uses: DOCX `style_name`, `heading_level`, `list_level`, bold/underline metadata, block_type, order.

## Chunking

- `AI_STRUCTURE_CHUNK_BLOCKS` (default 40)
- Context before/after
- Max characters per request
- LLM only for uncertain / conflicting blocks when `AI_STRUCTURE_LLM_ENABLED=true`

## Prompt

- Key: `military_structure_agent_v1`
- Version: `1.0.0`
- JSON-only output with evidence; schema validation in `structure/schema.py`

## Database tables

- `ai_training_structure_runs`
- `ai_training_document_structures`
- `ai_training_structure_corrections`
- `ai_training_document_outlines`
- `ai_training_structure_events`

Document columns added: `structure_status`, `latest_structure_run_id`, `structure_approved_*`, `structure_locked`.

Migration: `scripts/migrate_structure_b21.py`

## Structure lifecycle

`NOT_STARTED → QUEUED → RUNNING → NEEDS_REVIEW → REVIEW_COMPLETED → APPROVED_STRUCTURE`  
(also `FAILED`, `COMPLETED_WITH_WARNINGS`)

Separated from Extraction Approval.

## Review / Approval

- Single button: **اعتماد البنية العسكرية**
- Locks Structure Run; reanalysis creates a new run
- No institutional learning
- Extraction approval unchanged

## APIs

Under `/api/ai/training/documents/<id>/structure/...`:

analyze, reanalyze, GET structure/runs/outline/review, review start/save/complete, approve, events

UI: `/ai-center/training/documents/<id>/structure`

## Permissions

`AI_STRUCTURE_VIEW|ANALYZE|REVIEW|APPROVE|REANALYZE|AUDIT_VIEW` (system_admin)

## Configuration

See `app/ai_training/structure_config.py` (`AI_STRUCTURE_*`).

## Testing

`tests/test_ai_structure_b21.py` — rules, chunking, schema, validator, agent registration, review/approve lock, blocks unchanged.

## Limitations

- DOCX often has a single logical page; visual A4 pagination is UI-only.
- Font size / exact Word indentation often absent from extraction metadata.
- Qwen is assistive only; offline rules remain the primary path.
- Header/footer detection relies on block_type from extraction.

## Future Phase B2.2

Start from `APPROVED_STRUCTURE` documents only. Candidate next agent: Terminology — still must not rewrite original text or alter extraction/structure approvals without explicit revision runs.
