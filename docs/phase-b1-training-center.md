# Phase B1 — Training Center & Document Ingestion

## Purpose

Build offline training document infrastructure: upload, store originals immutably, extract text deterministically, human review of extraction quality, and a single **Approve Extraction Quality** action.

This phase does **not** teach institutional knowledge, terminology, staff duties, or generate reports.

## Scope

In scope: Training Center UI, Document Library, versioning fields, processing queue via Agentic workflow, Document Ingestion Agent, DOCX/PDF/TXT extractors, review + approval of extraction.

Out of scope: Structure/Terminology/Unit/Staff Duties/Validation agents, Institutional Memory, RAG, Vector DB, OCR, Cloud APIs, Phase B2.

## Architecture

```
AI Center → Training Center
              ↓
         Document Upload (secure)
              ↓
         Storage originals/ (immutable)
              ↓
         Workflow document_ingestion
              ↓
         Document Ingestion Agent (deterministic parsers)
              ↓
         Pages + Blocks + extracted.json
              ↓
         Human Review → Approve Extraction Quality
```

LLM assistance default: `AI_INGESTION_LLM_ASSISTED=false` (not used in B1 path).

## Document lifecycle

UPLOADED → QUEUED → PROCESSING → NEEDS_REVIEW → REVIEWED → APPROVED_EXTRACTION  
Failures → FAILED · Archive → ARCHIVED  
PDF image-only → PARTIAL_SUCCESS + OCR_REQUIRED warning (needs review)

## Storage

`{data_dir}/instance/ai_training/{originals,extracted,previews,temp,failed}/{document_uuid}/`

Override: `AI_TRAINING_STORAGE_PATH`

## Supported files

docx, pdf, txt · max size `AI_TRAINING_MAX_FILE_SIZE_MB` (default 50)

## Migration

```bat
.venv\Scripts\python.exe scripts\migrate_training_center.py migrate-training-center
.venv\Scripts\python.exe scripts\migrate_training_center.py verify-training-center-migration
```

Rollback (drop B1 tables only):

```bat
.venv\Scripts\python.exe scripts\migrate_training_center.py rollback-training-center --drop-tables-only
```

## Permissions

`can_ai_training_center_view`, `_document_upload`, `_document_review`, `_document_approve`, `_document_archive`, `_workflow_run`, `_audit_view` (system_admin)

## Approval meaning

`APPROVED_EXTRACTION` = human confirmed extraction fidelity. **Does not** update institutional memory or train the model.

## Future Phase B2

Structure / Terminology / Unit / Content classification agents consuming approved extraction blocks.
