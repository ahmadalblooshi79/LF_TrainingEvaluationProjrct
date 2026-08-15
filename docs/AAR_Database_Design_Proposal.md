# AAR Database Design Proposal

**Status:** Design only — **NO tables created, NO migrations, NO DB modifications**  
**Based on:** Phase 0 report (`docs/AAR_Pre_Implementation_Database_Architecture_Report.md`)  
**Date:** 2026-08-15  

**Gate:** Await approval before backup / DDL / Flutter schema bump / implementation.

---

## Design principles (binding)

| Rule | Application |
|------|-------------|
| Reuse first | Objectives, lists, results, notes, media, users, units stay in existing tables |
| Reference second | AAR stores FKs / composite pointers, not copied text/scores/files |
| Create only AAR-specific | Reviews, points, source links, analysis text, slides, versions, audit |
| No second sync | Tablet uses `pending_ops` + server `tablet_client_ops` |
| No second AI | Future assist via `ai_local_engine` only |
| Hub entry | Reuse analyst slug `after-action-review` |

---

## Minimal extension summary

**8 new server tables** (plus optional 9th audit if not folded into analysis events).  
**1 new tablet table** + **offline DB version 4 → 5**.  
**0** new tables for notes / evaluations / media / users / units / objectives / sync engine.

---

# PART A — Proposed NEW server tables

## A1. `aar_reviews`

### Purpose
One AAR workspace document per exercise (current draft), with status and metadata. Versions of an approved package live in `aar_versions` (snapshot metadata), not duplicated exercise data.

### Why cannot reuse existing
No table represents “After Action Review workspace / approval lifecycle” today. Analyst hub item `after-action-review` is UI-only placeholder.

### Columns

| Column | Type | Notes |
|--------|------|--------|
| `id` | INTEGER PK AUTOINCREMENT | |
| `exercise_id` | INTEGER NOT NULL | FK → `exercises.id` ON DELETE CASCADE |
| `status` | VARCHAR(32) NOT NULL DEFAULT `'draft'` | `draft\|under_review\|ready_for_approval\|approved` |
| `title` | VARCHAR(500) DEFAULT `''` | Optional display title |
| `completion_pct` | FLOAT NULL | Cached UI metric; recomputable |
| `current_version_label` | VARCHAR(32) DEFAULT `'0.1'` | e.g. `1.0` after approve |
| `created_by_id` | INTEGER NULL | FK → `users.id` ON DELETE SET NULL |
| `updated_by_id` | INTEGER NULL | FK → `users.id` ON DELETE SET NULL |
| `approved_by_id` | INTEGER NULL | FK → `users.id` ON DELETE SET NULL |
| `approved_at` | DATETIME NULL | |
| `created_at` | DATETIME NOT NULL | |
| `updated_at` | DATETIME NOT NULL | |

### Keys / indexes
- **PK:** `id`
- **UQ:** `uq_aar_reviews_exercise` (`exercise_id`) — one active review row per exercise (revisions tracked in `aar_versions`)
- **IX:** `ix_aar_reviews_status` (`status`)

### Relationships
`exercises` 1 — 1 `aar_reviews` → N `aar_points`, N `aar_analysis_blocks`, N `aar_slides`, N `aar_versions`

---

## A2. `aar_points`

### Purpose
Professional AAR conclusion item: **SUSTAIN** or **IMPROVE**. Owned by creating judge (or analyst after merge). Does **not** store evaluation scores or note bodies — only AAR fields + FKs.

### Why cannot reuse existing
- `judge_polarity_notes` = positives/negatives list (shared unit notes), not Sustain/Improve workflow with review status.
- Payload `rows[].notes` = criterion notes inside evaluation JSON, not AAR points.
- Merging / approval / slide inclusion are AAR-specific.

### Columns

| Column | Type | Notes |
|--------|------|--------|
| `id` | INTEGER PK AUTOINCREMENT | |
| `client_uuid` | VARCHAR(120) NOT NULL DEFAULT `''` | Idempotent tablet sync (mirror polarity pattern) |
| `aar_review_id` | INTEGER NOT NULL | FK → `aar_reviews.id` ON DELETE CASCADE |
| `exercise_id` | INTEGER NOT NULL | FK → `exercises.id` ON DELETE CASCADE (denormalized for queries) |
| `created_by_user_id` | INTEGER NOT NULL | FK → `users.id` — judge (or analyst for master) |
| `unit_level_key` | VARCHAR(64) NOT NULL DEFAULT `''` | Reuses string unit keys (no new units table) |
| `point_type` | VARCHAR(16) NOT NULL | `sustain` \| `improve` |
| `title` | VARCHAR(500) NOT NULL DEFAULT `''` | |
| `description` | TEXT NOT NULL DEFAULT `''` | AAR wording (may paraphrase; sources hold originals) |
| `analysis` | TEXT NOT NULL DEFAULT `''` | Optional judge/analyst analysis on the point |
| `recommendation` | TEXT NOT NULL DEFAULT `''` | Optional |
| `status` | VARCHAR(32) NOT NULL DEFAULT `'submitted'` | `submitted\|under_review\|approved\|rejected\|merged` |
| `master_point_id` | INTEGER NULL | FK → `aar_points.id` ON DELETE SET NULL — if merged into master |
| `include_in_presentation` | BOOLEAN NOT NULL DEFAULT 0 | |
| `training_objective_id` | INTEGER NULL | FK → `exercise_objectives.id` ON DELETE SET NULL |
| `evaluation_list_item_id` | INTEGER NULL | FK → `evaluation_list_pdf_items.id` ON DELETE SET NULL |
| `bundle_action_eval_id` | INTEGER NULL | FK → `exercise_planner_flow_bundle_action_evals.id` ON DELETE SET NULL |
| `primary_row_index` | INTEGER NULL | Soft link into `payload_json` rows when no polarity note |
| `dilemma_id` | INTEGER NULL | FK → `dilemma_items.id` ON DELETE SET NULL |
| `timeline_item_id` | INTEGER NULL | FK → `exercise_timeline_items.id` ON DELETE SET NULL |
| `planner_bundle_id` | INTEGER NULL | FK → `exercise_planner_flow_bundles.id` ON DELETE SET NULL |
| `flow_day_id` | VARCHAR(64) DEFAULT `''` | Soft ref into `flow_table_json` day id |
| `flow_row_index` | INTEGER NULL | Soft ref into flow JSON row |
| `created_at` | DATETIME NOT NULL | |
| `updated_at` | DATETIME NOT NULL | |

### Keys / indexes
- **PK:** `id`
- **UQ:** `uq_aar_points_creator_client_uuid` (`created_by_user_id`, `client_uuid`) — empty uuid avoided at write time (same rule as polarity)
- **IX:** `(aar_review_id, point_type)`, `(exercise_id, unit_level_key)`, `(created_by_user_id)`, `(status)`, `(master_point_id)`, `(training_objective_id)`

### Relationships
- Belongs to `aar_reviews` / `exercises` / `users`
- Optional soft/hard links to objective, list, action-eval, dilemma, timeline, planner bundle
- N sources via `aar_point_sources`
- N evidence via `aar_point_evidence`
- Merge: child points `master_point_id` → master point (`status='merged'` on children; master stays `approved` / `submitted`)

### SUSTAIN / IMPROVE representation
`point_type` enum string only — **not** a copy of `judge_polarity_notes.polarity`.  
Polarity notes may be **sources** of a point; positive≠sustain automatically (judge chooses Sustain/Improve explicitly).

---

## A3. `aar_point_sources` (bridge — critical for traceability)

### Purpose
Polymorphic-but-constrained links from an AAR Point to **existing** source records without duplicating content.

### Why cannot reuse existing
No join table maps “AAR conclusion ↔ original note/result/event”.

### Columns

| Column | Type | Notes |
|--------|------|--------|
| `id` | INTEGER PK AUTOINCREMENT | |
| `aar_point_id` | INTEGER NOT NULL | FK → `aar_points.id` ON DELETE CASCADE |
| `source_kind` | VARCHAR(32) NOT NULL | See vocabulary below |
| `judge_polarity_note_id` | INTEGER NULL | FK → `judge_polarity_notes.id` ON DELETE SET NULL |
| `evaluation_list_item_id` | INTEGER NULL | FK → `evaluation_list_pdf_items.id` ON DELETE SET NULL |
| `evaluation_saved_result_id` | INTEGER NULL | FK → `evaluation_list_saved_results.id` ON DELETE SET NULL |
| `planner_saved_result_id` | INTEGER NULL | FK → `planner_flow_bundle_eval_saved_results.id` ON DELETE SET NULL |
| `row_index` | INTEGER NULL | Criterion / payload row (no criterion_id in schema) |
| `criterion_label_snapshot` | VARCHAR(500) DEFAULT `''` | **Optional** cache of label at link time only if row deleted; prefer live resolve |
| `dilemma_id` | INTEGER NULL | FK → `dilemma_items.id` ON DELETE SET NULL |
| `timeline_item_id` | INTEGER NULL | FK → `exercise_timeline_items.id` ON DELETE SET NULL |
| `planner_bundle_id` | INTEGER NULL | FK → `exercise_planner_flow_bundles.id` ON DELETE SET NULL |
| `flow_day_id` | VARCHAR(64) DEFAULT `''` | Soft |
| `flow_row_index` | INTEGER NULL | Soft |
| `legacy_evaluation_note_id` | INTEGER NULL | FK → `evaluation_notes.id` ON DELETE SET NULL (rare) |
| `sort_order` | INTEGER NOT NULL DEFAULT 0 | |
| `created_at` | DATETIME NOT NULL | |

### `source_kind` vocabulary (aligned to real schema)
| Kind | Populated columns | Resolves to |
|------|-------------------|-------------|
| `polarity_note` | `judge_polarity_note_id` | `judge_polarity_notes` |
| `eval_row_note` | `evaluation_saved_result_id` + `row_index` (+ optional `evaluation_list_item_id`) | `payload_json.rows[i].notes` |
| `eval_row_score` | same | `payload_json.rows[i]` scores |
| `action_eval_row` | `planner_saved_result_id` + `row_index` | action-eval payload |
| `dilemma` | `dilemma_id` | `dilemma_items` |
| `timeline_event` | `timeline_item_id` | `exercise_timeline_items` |
| `flow_row` | `planner_bundle_id` + `flow_day_id` + `flow_row_index` | `flow_table_json` |
| `legacy_note` | `legacy_evaluation_note_id` | `evaluation_notes` |

### Keys / indexes
- **PK:** `id`
- **IX:** `(aar_point_id, source_kind)`, `judge_polarity_note_id`, `evaluation_saved_result_id`, `dilemma_id`
- **App-level check:** exactly the columns required for `source_kind` non-null (SQLite CHECK optional)

### Why this design
- **No criterion PK** exists → `row_index` + saved_result_id is the truthful pointer.
- **No first-class event row PK** for all flow rows → soft `flow_*` refs.
- Does not copy note text or scores.

---

## A4. `aar_point_evidence`

### Purpose
Mark existing media as evidence for a point / for AAR presentation — **reference only**.

### Why cannot reuse existing
Media tables have no `use_in_aar` flag; keeping flags on AAR side avoids touching core media schema.

### Columns

| Column | Type | Notes |
|--------|------|--------|
| `id` | INTEGER PK AUTOINCREMENT | |
| `aar_point_id` | INTEGER NULL | FK → `aar_points.id` ON DELETE CASCADE; NULL = review-level evidence only |
| `aar_review_id` | INTEGER NOT NULL | FK → `aar_reviews.id` ON DELETE CASCADE |
| `evidence_kind` | VARCHAR(16) NOT NULL | `criterion_media` \| `visual_document` |
| `evaluation_criterion_media_id` | INTEGER NULL | FK → `evaluation_criterion_media.id` ON DELETE CASCADE |
| `visual_document_id` | INTEGER NULL | FK → `visual_documents.id` ON DELETE CASCADE |
| `include_in_presentation` | BOOLEAN NOT NULL DEFAULT 1 | |
| `sort_order` | INTEGER NOT NULL DEFAULT 0 | |
| `created_by_user_id` | INTEGER NULL | FK → `users.id` ON DELETE SET NULL |
| `created_at` | DATETIME NOT NULL | |

### Keys / indexes
- **PK:** `id`
- **UQ partial intent:** unique (`evidence_kind`, media id, `aar_point_id`) enforced in app or composite unique where SQLite allows
- **IX:** `aar_review_id`, `aar_point_id`

---

## A5. `aar_analysis_blocks`

### Purpose
Editable analysis narrative for the review (Overall Performance, Conclusions, Recommendations, etc.) with optional source links via same source bridge pattern **or** embedded JSON refs to point IDs.

### Minimal columns

| Column | Type | Notes |
|--------|------|--------|
| `id` | INTEGER PK | |
| `aar_review_id` | INTEGER NOT NULL FK → `aar_reviews` | |
| `block_key` | VARCHAR(64) NOT NULL | `overall_performance`, `objective_achievement`, `key_sustain`, `key_improve`, `recurring_patterns`, `major_events`, `conclusions`, `recommendations`, … |
| `title` | VARCHAR(300) DEFAULT `''` | |
| `body` | TEXT DEFAULT `''` | Analyst-authored text |
| `linked_point_ids_json` | TEXT DEFAULT `'[]'` | JSON array of `aar_points.id` (simple; avoids N bridge for v1) |
| `updated_by_id` | INTEGER NULL FK → `users` | |
| `updated_at` | DATETIME | |
| `created_at` | DATETIME | |

### Keys
- **UQ:** `(aar_review_id, block_key)`

### Why not reuse
No existing “AAR narrative section” store. Report library AI tables are unrelated domain.

**v1 choice:** `linked_point_ids_json` instead of another bridge to keep table count low; can normalize later if needed.

---

## A6. `aar_event_classifications`

### Purpose
Analyst tags an existing event/dilemma/flow row for AAR inclusion without modifying planner JSON.

### Columns

| Column | Type | Notes |
|--------|------|--------|
| `id` | INTEGER PK | |
| `aar_review_id` | INTEGER NOT NULL FK | |
| `classification` | VARCHAR(32) NOT NULL | `sustain\|improve\|informational\|not_included` |
| `target_kind` | VARCHAR(32) NOT NULL | `dilemma\|timeline_event\|flow_row` |
| `dilemma_id` | INTEGER NULL FK → `dilemma_items` | |
| `timeline_item_id` | INTEGER NULL FK → `exercise_timeline_items` | |
| `planner_bundle_id` | INTEGER NULL FK → `exercise_planner_flow_bundles` | |
| `flow_day_id` | VARCHAR(64) DEFAULT `''` | |
| `flow_row_index` | INTEGER NULL | |
| `notes` | TEXT DEFAULT `''` | Classification rationale only |
| `updated_by_id` | INTEGER NULL | |
| `updated_at` | DATETIME | |

### UQ intent
One classification per (`aar_review_id`, target identity).

---

## A7. `aar_slides` + `aar_slide_items`

### Purpose
Lightweight slide builder structure; content is **references** to points/media/charts params, not embedded binaries.

### `aar_slides`

| Column | Type |
|--------|------|
| `id` | INTEGER PK |
| `aar_review_id` | INTEGER NOT NULL FK |
| `sort_order` | INTEGER NOT NULL |
| `slide_key` | VARCHAR(64) DEFAULT `''` | template key e.g. `cover`, `sustain` |
| `title` | VARCHAR(500) DEFAULT `''` |
| `is_hidden` | BOOLEAN DEFAULT 0 |
| `layout_key` | VARCHAR(64) DEFAULT `'default'` |
| `created_at` / `updated_at` | DATETIME |

### `aar_slide_items`

| Column | Type |
|--------|------|
| `id` | INTEGER PK |
| `aar_slide_id` | INTEGER NOT NULL FK → `aar_slides` ON DELETE CASCADE |
| `sort_order` | INTEGER NOT NULL |
| `item_type` | VARCHAR(32) NOT NULL | `title\|text\|bullets\|chart\|table\|image\|video_ref\|aar_point\|objective_summary\|evidence` |
| `text_body` | TEXT DEFAULT `''` | Only for free text/bullets authored in builder |
| `aar_point_id` | INTEGER NULL FK → `aar_points` |
| `aar_point_evidence_id` | INTEGER NULL FK → `aar_point_evidence` |
| `evaluation_criterion_media_id` | INTEGER NULL FK | |
| `visual_document_id` | INTEGER NULL FK | |
| `training_objective_id` | INTEGER NULL FK → `exercise_objectives` |
| `chart_key` | VARCHAR(64) DEFAULT `''` | e.g. `performance_by_unit` — data loaded live at render |
| `payload_json` | TEXT DEFAULT `'{}'` | Extra layout options only |

### Why cannot reuse
No presentation structure tables exist for AAR.

---

## A8. `aar_versions`

### Purpose
Immutable **metadata** of an approval/export snapshot (who/when/label/file path of pptx). Does not clone all points; optional `manifest_json` lists point IDs included at approve time.

### Columns

| Column | Type |
|--------|------|
| `id` | INTEGER PK |
| `aar_review_id` | INTEGER NOT NULL FK |
| `version_label` | VARCHAR(32) NOT NULL | `1.0`, `1.1` |
| `status` | VARCHAR(32) DEFAULT `'approved'` |
| `manifest_json` | TEXT DEFAULT `'{}'` | point ids, slide order snapshot |
| `pptx_relpath` | VARCHAR(700) DEFAULT `''` | export artifact path under data dir |
| `approved_by_id` | INTEGER NULL FK → `users` |
| `approved_at` | DATETIME NULL |
| `created_at` | DATETIME |

### UQ
`(aar_review_id, version_label)`

---

## A9. `aar_audit_logs` (recommended minimal)

### Purpose
AAR-specific audit (point created/merged/approved, export, AI suggestion accepted). Prefer **not** overloading `ai_audit_logs`.

### Columns
`id`, `exercise_id`, `aar_review_id` NULL, `user_id` NULL, `action` VARCHAR(64), `entity_type` VARCHAR(32), `entity_id` INTEGER NULL, `detail_json` TEXT, `created_at`

---

## Tables explicitly NOT proposed

| Rejected name | Reason |
|---------------|--------|
| `aar_judge_notes` | Use `judge_polarity_notes` + payload notes via `aar_point_sources` |
| `aar_evaluations` / score tables | Use `evaluation_list_saved_results` / planner saved results |
| `aar_media` / file store | Use `evaluation_criterion_media` / `visual_documents` |
| `aar_users` / `aar_units` / `aar_objectives` / `aar_evaluation_lists` | Existing tables |
| `aar_events` / `aar_dilemmas` | Existing + `aar_event_classifications` |
| Second sync / queue tables on server | Use `tablet_client_ops` |
| Permission ACL tables | Extend role helpers; hub slug `after-action-review` |

---

# PART B — Relationship map

Legend: **[E]** existing · **[N]** new

```
Exercise [E]
  ├─ ExerciseObjective [E]  ←── training_objective_id on aar_points [N]
  ├─ EvaluationListPdfItem [E]
  │     └─ EvaluationListSavedResult.payload_json [E]
  │           ├─ rows[i].notes / scores  ←── aar_point_sources (eval_row_*) [N]
  │           └─ EvaluationCriterionMedia [E] ←── aar_point_evidence [N]
  ├─ JudgePolarityNote [E] ←── aar_point_sources (polarity_note) [N]
  ├─ DilemmaItem / Timeline / flow_table_json [E]
  │     ←── aar_point_sources / aar_event_classifications [N]
  ├─ VisualDocument [E] ←── aar_point_evidence [N]
  └─ aar_reviews [N]
        ├─ aar_points [N]  (SUSTAIN | IMPROVE)
        │     ├─ aar_point_sources [N]  → original notes/results/events
        │     └─ aar_point_evidence [N] → original media
        ├─ aar_analysis_blocks [N]  (Analysis / Conclusion / Recommendation text)
        │     └─ linked_point_ids → aar_points
        ├─ aar_slides [N]
        │     └─ aar_slide_items [N] → points / evidence / objectives / chart_key
        ├─ aar_versions [N]
        └─ aar_audit_logs [N]
```

### Traceability path (as required)

```
AAR Slide [N]
  → aar_slide_items.aar_point_id
    → AAR Point [N]
      → aar_point_sources
        → Judge Note (polarity_note_id OR saved_result_id+row_index)
        → Evaluation Result (saved_result_id)
        → Criterion (row_index within that result — no separate criterion table)
        → Event/Dilemma (dilemma_id / timeline / flow soft ref)
      → aar_point_evidence
        → Photo/Video (criterion_media_id / visual_document_id)
    → Analysis block [N] (links point ids)
      → Conclusion / Recommendation (block_key)
```

**Existing today:** Exercise → Objective, List, Result JSON, Polarity notes, Media, Dilemmas/Flow.  
**New:** everything from `aar_reviews` downward in the chain.

---

# PART C — SUSTAIN / IMPROVE without duplicating notes

| Concept | Storage |
|---------|---------|
| Original note | Remains in `judge_polarity_notes` or `payload_json.rows[].notes` |
| AAR Point | New row in `aar_points` with `point_type=sustain\|improve` |
| Link | `aar_point_sources` row(s) |
| Merge | Children `status=merged`, `master_point_id=…`; originals retained |

Judge flow “اختر من ملاحظاتي” → creates point + source link(s), does not delete/alter the note.

---

# PART D — ANDROID OFFLINE DATABASE CHANGES

## Current: `tablet_offline.db` **v4**
Tables: `cache`, `pending_ops`, `media_files`, `local_users`, `device_meta`

## Required: bump to **v5**

### Why v5 is required
Need a durable local store for AAR points that survives restart and is not only ephemeral cache JSON. Additive `onUpgrade` from 4→5 mirrors prior upgrades (v2→v3→v4). **No destructive migration.**

### New tablet table: `aar_points_local`

| Column | Type | Notes |
|--------|------|--------|
| `client_uuid` | TEXT PK | Same id used as `pending_ops.id` / server `client_uuid` |
| `server_id` | INTEGER NULL | Filled after sync |
| `exercise_id` | INTEGER | |
| `unit_level_key` | TEXT | |
| `point_type` | TEXT | `sustain`/`improve` |
| `title` | TEXT | |
| `description` | TEXT | |
| `analysis` | TEXT | |
| `recommendation` | TEXT | |
| `status` | TEXT | local draft / submitted pending |
| `training_objective_id` | INTEGER NULL | |
| `evaluation_list_item_id` | INTEGER NULL | |
| `bundle_action_eval_id` | INTEGER NULL | |
| `primary_row_index` | INTEGER NULL | |
| `source_refs_json` | TEXT | Array of source descriptors (polarity client/server id, saved_result id + row, …) |
| `evidence_refs_json` | TEXT | Local `media_files.id` and/or server media ids |
| `sync_status` | TEXT | `pending\|syncing\|synced\|failed` |
| `updated_at` | TEXT | |
| `payload_json` | TEXT | Full body for POST idempotent replay |

### Reused tablet tables (no redesign)
| Table | Use for AAR |
|-------|-------------|
| `pending_ops` | Queue `POST/PUT/DELETE /api/tablet/aar-points…` with `op_type` e.g. `aar_point_save` / `aar_point_delete`; `id` = `client_uuid` |
| `media_files` | Local photo/video; evidence refs point to `media_files.id` until uploaded |
| `cache` | Optional cache of server AAR point list |
| `tablet_client_ops` (server) | Duplicate prevention via same idempotency key |

### Offline behaviors covered
| Requirement | Mechanism |
|-------------|-----------|
| Create/edit offline | Upsert `aar_points_local` + enqueue `pending_ops` |
| Link note | `source_refs_json` → polarity note uuid / eval row |
| Link evaluation | list item id + row_index / cache key |
| Link photo/video | `evidence_refs_json` → `media_files.id` (upload still via existing media pipeline) |
| Survive restart | sqflite persistence |
| Sync My Work | Existing `SyncService` loop; new op types |
| No duplicate upload | Same `client_uuid` / idempotency as polarity + `tablet_client_ops` |

### Not needed on tablet
Separate sync engine, second media table, local copy of full evaluation payloads beyond existing `cache`.

---

# PART E — MIGRATION PLAN (not executed)

1. **Human approval** of this design.  
2. **Backup** live `exercises.db` → timestamped copy under data dir (only after approval).  
3. Add SQLAlchemy models for A1–A9.  
4. Additive `ensure_aar_tables()` (pattern like AI/analyst ensures) + `create_all`.  
5. **No** DROP / DELETE / RESET.  
6. Flutter: `offline_store` version **5**, `CREATE TABLE IF NOT EXISTS aar_points_local`, wire repository/sync op types.  
7. Server tablet APIs: `/api/tablet/aar-points` CRUD upsert by `client_uuid`.  
8. Wire analyst route `after-action-review` to workspace (later phase).  
9. Permissions: start with `can_access_analyst_hub` / `can_access_judge_hub`; add fine-grained helpers only if required.

---

# PART F — FINAL PROPOSED TABLE LIST

## REUSED EXISTING TABLES
`exercises`, `users`, `exercise_objectives`, `exercise_roster_rows`, `judge_trainee_assignments`,  
`evaluation_list_pdf_items`, `evaluation_list_saved_results`, `planner_flow_bundle_eval_saved_results`,  
`evaluation_criterion_media`, `visual_documents`,  
`judge_polarity_notes`, `evaluation_notes` (legacy only via source),  
`dilemma_items`, `exercise_timeline_items`, `exercise_planner_flow_bundles`,  
`information_bank_unit_levels` / `UNIT_LEVELS`,  
`tablet_client_ops`,  
AI: `ai_settings` + `ai_local_engine` (future assist only)

## NEW SERVER TABLES
1. `aar_reviews`  
2. `aar_points`  
3. `aar_point_sources`  
4. `aar_point_evidence`  
5. `aar_analysis_blocks`  
6. `aar_event_classifications`  
7. `aar_slides`  
8. `aar_slide_items`  
9. `aar_versions`  
10. `aar_audit_logs`  

## NEW / CHANGED TABLET TABLES
- **New:** `aar_points_local`  
- **Changed:** DB version **4 → 5** (`onUpgrade` additive only)  
- **Unchanged structure:** `pending_ops`, `media_files`, `cache`, `local_users`, `device_meta` (new `op_type` values only)

## TABLES NOT NEEDED
`aar_judge_notes`, `aar_evaluations`, `aar_media`, `aar_users`, `aar_units`, `aar_objectives`, `aar_evaluation_lists`, `aar_events`, `aar_dilemmas`, second sync/queue tables, second Ollama integration tables

---

## Open decisions for your approval

1. **One `aar_reviews` row per exercise** (recommended) vs allow multiple concurrent reviews.  
2. **`linked_point_ids_json` on analysis blocks** (v1 simple) vs full `aar_analysis_sources` bridge now.  
3. **Criterion label snapshot** on sources: store empty and resolve live only (recommended) vs snapshot.  
4. **Who may approve AAR:** analyst only, or also control/chief/admin (permission helper scope).  
5. Confirm hub route remains **`/analyst/after-action-review`** (existing slug) rather than `/analysis/aar`.

---

## Stop point

This document is the **AAR Database Design Proposal** only.

- No tables created  
- No migrations run  
- `exercises.db` untouched  
- `tablet_offline.db` untouched  
- No backup created  

Await your approval (and answers to open decisions) before Phase: Backup → Migration → Implementation.
