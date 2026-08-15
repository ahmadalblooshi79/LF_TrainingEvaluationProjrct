# AAR Pre-Implementation Database & Architecture Report

**Status:** Phase 0 complete — **no AAR tables / migrations / routes implemented yet**  
**Date:** 2026-08-15  
**Gate:** Implementation must not start until this report is reviewed and backup is taken.

---

## 1. Database file(s) discovered

| Item | Value |
|------|--------|
| Active DB | `C:\Users\USER\AppData\Local\LF_TrainingEvaluation\exercises.db` |
| Config source | `app.config.DATABASE_URL` → `sqlite:///{data_dir}/exercises.db` |
| Data directory | `app.paths.data_dir()` → `%LOCALAPPDATA%\LF_TrainingEvaluation` (installed/runtime) |
| Repo copy | `exercises.db` in project root may exist but is **not** the live DB |
| Table count | **83** tables (SQLAlchemy `create_all` + additive `ALTER` helpers; **no Alembic**) |
| Schema dump (raw) | `docs/AAR_Pre_Implementation_DB_raw.json` |

**Migration style today:** additive only (`Base.metadata.create_all` + `app/database.py` / AI `ensure_*_tables`). No versioned migration framework.

---

## 2. Relevant existing tables (grouped)

### Core exercise / users
- `exercises`, `users`, `role_defs`
- `exercise_objectives`, `exercise_roster_rows`, `exercise_battle_unit_personnel`
- `judge_trainee_assignments`, `judge_incomplete_task_status`

### Evaluation
- `evaluation_list_pdf_items` (list metadata + `pdf_relpath` / Excel path)
- `evaluation_list_saved_results` (**canonical scores** in `payload_json`)
- `evaluation_criterion_media` (photo/video per criterion row)
- `evaluation_notes` (legacy free-text notes: `exercise_id` + `user_id` + `body` only)
- `judge_polarity_notes` (positives/negatives entered by judges — **recent**)
- `planner_flow_bundle_eval_saved_results` (action-eval sheet results)

### Events / dilemmas / flow
- `exercise_planner_flow_bundles` (+ `flow_table_json` for days/rows)
- `exercise_planner_flow_bundle_event_flows`
- `exercise_planner_flow_bundle_action_evals`
- `dilemma_items`
- `exercise_timeline_items`
- `event_flows`, `problems` (older/alternate models)
- `analyst_flow_day_phase_links`

### Units / Information Bank
- `information_bank_unit_levels`, `information_bank_training_phases`
- `information_bank_tree_nodes`, dilemma/eval/xlsx/pdf bank tables
- `unit_designations`, `unit_designation_aliases`

### Media / chat / notifications
- `visual_documents`, `chat_*`, `exercise_notifications`

### Tablet sync
- `tablet_client_ops` (idempotent client ops)

### AI Center (separate domain)
- `ai_settings`, `ai_agents`, `ai_agent_runs`, `ai_workflow_runs`, `ai_audit_logs`, report library + training tables…

---

## 3. Relevant columns (high-signal)

### `exercises`
`id`, `code`, `title`, `planned_start`, `planned_end`, `status`, `owner_id`, mission/location fields, …

### `exercise_objectives`
`id`, `exercise_id` (FK), `sort_order`, `text` — **no achievement % column** (computed from evaluations).

### `users` / roles
`id`, `username` (**military number for judges**), `full_name`, `password_hash`, `role_key` (`system_admin|analyst|planner|judge|chief_judge|control|standards_library`), `is_active`.

### `exercise_roster_rows`
`military_number`, `rank_ar`, `full_name`, `unit_level_key`, `roster_kind` (`trainee|judge`).

### `evaluation_list_pdf_items`
`exercise_id`, `exercise_phase`, `unit_level_key`, `text`, `pdf_relpath`, `sort_order`.

### `evaluation_list_saved_results`
`evaluation_item_id`, `exercise_id`, `unit_level_key`, `payload_json` (rows: acquired/notes/percents), `total_pct`, `grade_label`,  
approval flags: `is_approved`, `is_chief_approved`, `is_control_approved`, reopen flag, timestamps, saver/approver user FKs.

### `evaluation_criterion_media`
`exercise_id`, `unit_level_key`, `evaluation_list_item_id` **or** `bundle_action_eval_id`, `row_index`, `media_kind`, `mime_type`, `file_relpath`, `uploaded_by_id`, `client_op_id`.

### `judge_polarity_notes`
`client_uuid`, `exercise_id`, `judge_user_id`, `unit_level_key`, `polarity` (`positive|negative`), `body`, `source_kind` (`general|criterion|action_eval`), optional `evaluation_list_item_id` / `bundle_action_eval_id`, `row_index`, `criterion_label` (**label text, not criterion FK**).

### `visual_documents`
`exercise_id`, optional `event_id` → `exercise_timeline_items`, optional `dilemma_id` → `dilemma_items`, `unit_level_key`, `uploaded_by_id`, `file_type`, `file_relpath`, description/location.

### `tablet_client_ops`
`user_id`, `client_op_id` (unique per user), `op_type`, `path`, `response_json`, `exercise_id`, timestamps — duplicate prevention for tablet APIs.

---

## 4. Existing relationships (map)

```
Exercise
  ├─ ExerciseObjective (1:N)  [text only]
  ├─ ExerciseRosterRow (judges/trainees + unit_level_key)
  ├─ JudgeTraineeAssignment (judge user ↔ unit / bundle)
  ├─ EvaluationListPdfItem (unit + phase)
  │     └─ EvaluationListSavedResult (payload_json rows)
  │           └─ EvaluationCriterionMedia (by list_item_id + row_index)
  ├─ ExercisePlannerFlowBundle (phase + unit)
  │     ├─ flow_table_json (days / event rows)
  │     ├─ EventFlow slots / ActionEval slots
  │     └─ PlannerFlowBundleEvalSavedResult + criterion media via bundle_action_eval_id
  ├─ DilemmaItem (unit-scoped files)
  ├─ ExerciseTimelineItem
  ├─ JudgePolarityNote (exercise + unit + judge; optional list/action links)
  ├─ EvaluationNote (exercise + user; weak linkage)
  └─ VisualDocument (optional event/dilemma)
```

**Units** are string keys (`unit_level_key`), not numeric FKs to a single “units” table — catalog in `information_bank_unit_levels` / runtime `UNIT_LEVELS`.

**Criteria** are **not** first-class rows in SQL for judge sheets: they live inside Excel structure + `payload_json` rows (`row_index`). Analyst side has separate criteria allocation tables.

---

## 5. Training Objective storage

| Fact | Detail |
|------|--------|
| Table | `exercise_objectives` |
| Fields | `id`, `exercise_id`, `sort_order`, `text` |
| Missing for AAR | No FK from evaluations/notes/events → objective; no stored achievement % |
| Implication | AAR must **bridge** objectives to evaluations/points (new bridge or soft mapping), not assume existing links |

---

## 6. Evaluation storage

| Layer | Storage |
|-------|---------|
| List catalog | `evaluation_list_pdf_items` (+ files under `EVALUATION_LIST_XLSX_DIR` / planner dirs) |
| Scores / row notes | `evaluation_list_saved_results.payload_json` |
| Action-eval scores | `planner_flow_bundle_eval_saved_results` |
| Analyst matrices | `analyst_evaluation_criteria_*`, dilemma criteria, final-eval allocation tables |
| Approvals | columns on saved-result tables (judge → chief → control) |

There is **no** `evaluations` table with one row per criterion score; the canonical unit of score data is **saved result + JSON rows**.

---

## 7. Judge Notes storage (critical for AAR)

Three distinct concepts exist today:

| Kind | Table / location | Links |
|------|------------------|-------|
| **Criterion row notes** | Inside `evaluation_list_saved_results.payload_json` → `rows[].notes` | Implicit: list item + `row_index`; no `judge_note_id` |
| **Polarity notes** (إيجابيات/سلبيات) | `judge_polarity_notes` | `exercise_id`, `judge_user_id`, `unit_level_key`; optional list/action + `row_index` + `criterion_label` |
| **Legacy evaluation_notes** | `evaluation_notes` | `exercise_id`, `user_id`, `body` only |

**Missing vs AAR ideal note model:**
- No stable `evaluation_criterion_id`
- No `training_objective_id` on notes
- Criterion notes are **not addressable rows** (only JSON) — AAR sources should reference `(evaluation_list_saved_result_id or evaluation_item_id, row_index)` or polarity_note_id, **not** copy text into `aar_judge_notes`

**Do not create `aar_judge_notes`.** Use references:
- `judge_polarity_note_id` and/or
- `(evaluation_item_id|saved_result_id, row_index)` for payload notes.

---

## 8. Events / Dilemmas storage

| Concept | Actual storage |
|---------|----------------|
| Planner “مجرى الأحداث والمعاضل” package | `exercise_planner_flow_bundles` |
| Days / flow rows | primarily `flow_table_json` (+ related event-flow slot files) |
| Action evaluation lists | `exercise_planner_flow_bundle_action_evals` + saved results |
| Dilemma files (unit) | `dilemma_items` (`pdf_relpath`, `unit_level_key`, `exercise_id`) |
| Timeline | `exercise_timeline_items` |
| Analyst day↔phase | `analyst_flow_day_phase_links` |
| Older models | `event_flows`, `problems` |

**No single numeric `event_id` for every flow row** in SQL — many “events” are JSON rows. AAR classification should reference bundle + day id + row index (or timeline/dilemma IDs when present).

---

## 9. Photo / Video storage

| Source | Metadata table | Bytes on disk |
|--------|----------------|---------------|
| Criterion evidence | `evaluation_criterion_media.file_relpath` | `EVAL_CRITERION_MEDIA_DIR` (`instance/eval_criterion_media`) |
| Visual documentation hub | `visual_documents.file_relpath` | `VISUAL_DOC_DIR` |
| Chat attachments | chat tables + `CHAT_UPLOAD_DIR` | |
| Android local | `media_files.local_path` under app documents `media/pending|synced/...` | then chunked upload to server |

**DB stores paths / mime / kind / uploader — not BLOBs.**  
Reuse these tables via FK / `media_id` references; do not invent a second media store.

---

## 10. Android local database architecture

| Item | Value |
|------|--------|
| Engine | `sqflite` (not Room) |
| DB name | `tablet_offline.db` |
| Version | **4** (`OfflineStore`) |
| Tables | `cache`, `pending_ops`, `media_files`, `local_users`, `device_meta` |
| Sync statuses | `pending|syncing|synced|failed|conflict` |
| Idempotency | `pending_ops.id` = client UUID / op id |
| Media | file paths + `sync_status` + optional server confirmation |
| Notes / evals | primarily in **cache JSON** keyed by API resources, not normalized local note tables |
| Polarity notes | cached via repository + pending POST/DELETE to `/api/tablet/polarity-notes` |

**Implication for Offline AAR Points:** extend `pending_ops` + local table(s) additive (new version **5**), reuse same Sync My Work pipeline — **do not** build a second sync stack.

---

## 11. Existing synchronization architecture

**Direction Tablet → Server (manual):**
- UI: Sync My Work / SyncService
- Queue: `pending_ops` → HTTP method/path/body
- Idempotency: `Idempotency-Key` / `client_op_id` ↔ server `tablet_client_ops`
- Media: resumable `/api/tablet/media/upload/{init,chunk,status,complete}`

**Direction Server → Tablet:**
- Device package: `GET /api/tablet/device/package`
- Bootstrap / per-resource GET cache
- `GET /api/tablet/me/updates`

**Key tablet APIs already present:** auth, flow, action-eval, evaluation-lists (+ results/approve), objectives, incomplete, media, library, notifications, polarity-notes, device setup.

**AAR Points sync:** add new op types + endpoints mirroring polarity-notes pattern (`client_uuid`, upsert, scoped by judge).

---

## 12. Existing permission architecture

- **Role-centric** helpers in `app/permissions.py` (not a fine-grained ACL table).
- Analyst hub: `can_access_analyst_hub` = analyst **or** system_admin.
- Judge hub / save eval: judge / chief / admin (+ planner for some).
- AI Center: **system_admin only** (`can_access_ai_center`).

**Already in analyst menu (placeholder only):**  
`ANALYST_HUB_ITEMS` includes `("after-action-review", "إنشاء مراجعة ما بعد العمل", …)` → currently falls through to placeholder unless implemented.

**Recommended route alignment:**  
Prefer `/analyst/after-action-review` (or slug `aar`) under existing analyst hub — **not** a new top-level `/analysis/` space (unless product insists). Spec’s `/analysis/aar` should map to existing hub conventions.

**New AAR capabilities** should be added as helpers (e.g. `can_aar_view`, `can_aar_approve`) composed from roles — **not** a parallel auth system. Spec names `aar_view|create|edit|review|approve|export|ai_assist` fit as permission helpers.

---

## 13. Existing Local AI integration

| Component | Path / role |
|-----------|-------------|
| Hub UI | `/ai-center` (+ settings, models, test prompt) |
| Engine | `app/ai_local_engine` — providers: **Ollama**, LM Studio, llama.cpp |
| Settings table | `ai_settings` |
| Report library | `app/ai_report_library` |
| Agentic | `app/ai_agentic` |
| Training | `app/ai_training` |
| Access | system admin only today |

**AAR AI assist** must call the same `AIService` / provider gateway; degrade gracefully when Ollama is down.  
Note: older `positives_negatives_ai.py` / OpenAI env still exist for other features — **control/analyst PN pages no longer use AI** (judge-sourced). Do not wire AAR to OpenAI cloud.

---

## 14. Existing functionality that can be reused

- Analyst hub shell + hub menu item `after-action-review`
- Exercise context (`_current_workspace_exercise`)
- Objectives list UI patterns (`admin_exercise_objectives`)
- Evaluation dashboards/charts patterns (analyst evaluation-results)
- Judge polarity notes UX (list + unit scope) as a **pattern** for AAR points (but separate entity)
- Criterion media + visual docs as evidence sources
- Tablet offline queue + idempotent APIs
- AI Center gateway for optional suggestions
- `python-pptx` candidate for export (not yet verified as dependency — check `requirements` before implementing)

---

## 15. Missing relationships (for AAR)

| Desired link | Status |
|--------------|--------|
| Objective ↔ Evaluation list/criterion | **Missing** (needs bridge or mapping rules) |
| Objective ↔ Event/Dilemma | **Missing** (except soft/analyst conventions) |
| Addressable Judge Note ID for payload notes | **Missing** (JSON only) |
| AAR Point / Review / Slides / Versions / Approvals | **Missing entirely** |
| Similar-point merge / master point | **Missing** |
| Evidence “use in AAR” flag | **Missing** (can be AAR-side reference table) |
| Day as first-class FK for all evals | Partial (phase + flow JSON days) |

---

## 16. New tables genuinely required (proposal — **not created yet**)

Additive AAR layer only (names indicative):

1. `aar_reviews` — one (or versioned) AAR per `exercise_id` + status/completion  
2. `aar_points` — Sustain/Improve points (`point_type`, title, description, status, judge/unit/exercise FKs, optional objective/list/row refs)  
3. `aar_point_sources` — polymorphic links to polarity_note / (list_item,row) / event refs / dilemma_id  
4. `aar_point_evidence` — links to `evaluation_criterion_media.id` / `visual_documents.id`  
5. `aar_point_merges` or master_point_id on points — keep originals  
6. `aar_analysis_sections` — editable analysis/conclusions/recommendations text + source links  
7. `aar_event_classifications` — Sustain/Improve/Info/NotIncluded for flow/dilemma refs  
8. `aar_slides` + `aar_slide_items` — presentation structure referencing AAR data IDs  
9. `aar_versions` / `aar_approvals` — approval metadata  
10. `aar_audit_logs` — or reuse/extend `ai_audit_logs` only if semantically wrong; prefer dedicated `aar_audit_logs`  
11. Optional: `aar_objective_links` if many-to-many needed  

**Do not create:** duplicate objectives, evaluations, media blobs, users, units, event copies, `aar_judge_notes`.

---

## 17. Existing tables requiring safe extension (optional)

| Table | Possible additive columns | Risk |
|-------|---------------------------|------|
| `judge_polarity_notes` | `training_objective_id` nullable | Low if nullable |
| `evaluation_criterion_media` | none required if AAR evidence link table used | — |
| `exercise_objectives` | none required initially | — |
| Flutter `tablet_offline.db` | new tables + pending op types (v5) | Must stay additive; **no destructive migration** |

Prefer **bridge tables** over altering core eval payload format.

---

## 18. Required migrations (plan only)

1. Timestamped backup of live `exercises.db` (e.g. `exercises_before_aar_YYYYMMDD_HHMM.db` under data dir) — **not done in this phase**  
2. Additive SQLAlchemy models + `create_all` / `ensure_aar_tables()` following AI/analyst pattern  
3. No DROP/DELETE/RESET  
4. Flutter DB version bump with `CREATE TABLE IF NOT EXISTS` only  
5. New tablet API routes under `/api/tablet/aar-...` with `tablet_client_ops` idempotency  

---

## 19. Potential duplication risks

- Treating polarity notes as AAR points automatically → **forbidden by product rule**; link only  
- Copying payload notes into AAR tables → breaks single source of truth  
- Second media library / second sync queue  
- Parallel `/analysis` hub vs existing `/analyst`  
- Rebuilding objectives/events already in planner bundles  

---

## 20. Potential compatibility risks

- Changing `payload_json` shape for criteria IDs → can break eval UI/tablet  
- Restricting polarity note visibility while AAR expects shared unit notes  
- Offline AAR without package/bootstrap fields → incomplete offline create  
- Approval workflow conflicting with eval approval naming  
- AI assist permissions wider than current AI Center (admin-only) — product must decide if analysts get `aar_ai_assist`  

---

## Implementation Gate checklist

| Step | Status |
|------|--------|
| Existing system inspection | Done |
| Database inspection | Done |
| Android DB inspection | Done |
| Synchronization inspection | Done |
| Permission inspection | Done |
| AI Center inspection | Done |
| Relationship map | Done |
| Duplication check | Done |
| Pre-implementation report | **This document** |
| Backup before migration | **Pending (next step before any DDL)** |
| Migration plan approval | **Awaiting decision** |
| START AAR implementation | **Blocked until gate cleared** |

---

## Recommended first implementation slice (after approval + backup)

1. Backup live DB  
2. `aar_reviews` + `aar_points` + `aar_point_sources` (+ evidence links)  
3. Permission helpers + `/analyst/after-action-review` workspace shell (tabs stub)  
4. Judge web AAR points CRUD (own points only)  
5. Tablet offline points + sync API  
6. Then central review / merge / evidence / slides / pptx / AI assist  

---

## Confirmation

- **No AAR tables were created in this phase.**  
- **No routes/APIs/migrations for AAR were implemented.**  
- Existing system behavior was not changed for this report (inspection + documentation only).  
- Temporary inspection artifact: `docs/AAR_Pre_Implementation_DB_raw.json` (+ optional cleanup of `_tmp_aar_inspect_db.py`).
