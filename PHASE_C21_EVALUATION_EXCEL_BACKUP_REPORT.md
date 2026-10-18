# PHASE C.2.1 — EVALUATION EXCEL BACKUP

**Version:** 2.7.38+52  
**applicationId:** `ae.lf.training.lf_training_evaluation`  
**SQLite schema:** 4  
**Date:** 2026-10-17

2.7.37+51 was already built before this amendment (per-list folders + associated media). Version incremented to 2.7.38+52.

---

## Architecture check

Original military Excel templates live on the Flask server (`app/evaluation_list_export.py` + openpyxl writing into information-bank / `evaluation_list_xlsx` files). Those `.xlsx` templates are **not** stored on the tablet.

On the tablet, قوائم تقييم الإجراءات and قوائم تقييم المعاضل are already parsed into local cache:

- Procedure: `u{userId}:evaluation_list_detail:{unit}:{itemId}`
- Dilemma: `u{userId}:action_eval_detail:{slotId}`
- Scores/notes: `saved_payload.rows` / pending `save_results` (`المكتسبة`, `الملاحظات`)
- Criteria: `eval_rows` from the parsed template

Existing offline Excel generator (reused, no new engine, no new dependency):

- `flutter_app/lib/services/eval_backup_assembler.dart` → `assembleEvalBackup`
- `flutter_app/lib/services/local_recovery_xlsx.dart` → `buildSimpleXlsx`

This is the established tablet Excel format for evaluation-list backup. It includes criteria, المكتسبة, and الملاحظات from local data. It does not mutate approval, pending_ops, or trigger sync.

Media association uses existing local identifiers only:

- Procedure lists: `evaluation_list_item_id` == list `evalItemId`
- Dilemma lists: `bundle_action_eval_id` == list `evalItemId`
- Plus `exercise_id` + `user_id` when present

No filename / directory / judge-name / date guessing.

---

## Checklist

Existing Procedure Evaluation Excel Architecture Found: **YES**

Existing Dilemma Evaluation Excel Architecture Found: **YES**

Procedure Excel Source: `eval_backup_assembler.assembleEvalBackup` from local cache `evaluation_list_detail` + pending `save_results`; `local_recovery_xlsx.buildSimpleXlsx`

Dilemma Excel Source: same assembler from local cache `action_eval_detail` + pending action-eval `save_results`; `local_recovery_xlsx.buildSimpleXlsx`

Offline Excel Generation: **PASS**

Procedure Evaluation Excel Included: **PASS**

Dilemma Evaluation Excel Included: **PASS**

Unrelated Excel Excluded: **PASS**

Information Bank Excel Excluded: **PASS**

Current Exercise Isolation: **PASS**

Selected User Isolation: **PASS**

Current Local Scores Included: **PASS**

Current Local Notes Included: **PASS**

Original Excel Formatting Preserved: **PASS** (existing tablet evaluation-list workbook layout: عناصر التقييم / القصوى / المكتسبة / الملاحظات)

Excel Files Open Normally: **PASS** (valid XLSX / ZIP PK)

Excel Files SHA-256 Verified: **PASS**

Existing Technical Backup Preserved: **PASS** (`backup_manifest.json`, `BACKUP_COMPLETE`, `records/`, `media/`)

Restore Architecture Changed: **NO** (list folders are human-readable only; restore still uses records/media + manifest)

Phase C.1 OOM Fix Preserved: **PASS**

Phase C.2 Downloads Storage Preserved: **PASS**

Phase C.2 User Search Preserved: **PASS**

Database Schema Changed: **NO**

Migration Created: **NO**

New Dependency: **NO**

Phase B Regression: **PASS**

Evaluation List Folder Per List: **PASS**

Folder Uses Evaluation List Name: **PASS**

Excel Stored With Its List: **PASS**

Images Stored With Correct List: **PASS**

Videos Stored With Correct List: **PASS**

Stable Media-to-List Association: **PASS**

Cross-List Media Leakage: **PASS**

Cross-User Media Leakage: **PASS**

Cross-Exercise Media Leakage: **PASS**

Large Video Streaming: **PASS**

Original Media Unchanged: **PASS**

Technical Restore Compatibility: **PASS**

APK: `dist/judge-tablet-v2.7.38.apk`

APK Installed: **NO**

Production Tablet Accessed: **NO**

Physical Test Required: **YES**

---

## Backup layout

```
Backup_<timestamp>/
├── backup_manifest.json
├── BACKUP_COMPLETE
├── records/
├── media/
└── قوائم التقييم/
    ├── قوائم تقييم الإجراءات/
    │   └── <List Display Name>/
    │       ├── <List Display Name>.xlsx
    │       ├── <associated image>
    │       └── <associated video>
    └── قوائم تقييم المعاضل/
        └── <List Display Name>/
            ├── <List Display Name>.xlsx
            └── <associated media>
```

Technical Restore still uses `records/` + `media/` + `backup_manifest.json`. Human-readable list folders duplicate associated media by copy only.

Inventory kinds:

- `procedure_evaluation_excel`
- `dilemma_evaluation_excel`
- `procedure_evaluation_image` / `procedure_evaluation_video`
- `dilemma_evaluation_image` / `dilemma_evaluation_video`

Excel inventory entries store:

- `evaluation_type` (`procedure` / `dilemma`)
- `evaluation_list_id`
- `exercise_id`
- `user_id`
- `display_name`
- relative path / size / SHA-256

Media inventory entries additionally store:

- `evaluation_item_id` (`row_index` when present)
- `media_id`
- `media_type`
- `source_local_path`

Folder names are not identity. Duplicate display names get `(L{id})` only when required. Duplicate media filenames get `_2` suffix.

Success text shows:

- `تم إنشاء النسخة الاحتياطية بنجاح`
- real Downloads location
- `قوائم تقييم الإجراءات: X`
- `قوائم تقييم المعاضل: Y`
- `الصور: X`
- `الفيديوهات: X`

---

## Tests

- `flutter_app/test/phase_c21_evaluation_excel_backup_test.dart` — 10 passed (per-list folders, associated media isolation, duplicate names/filenames, 8 MB streamed video, original media unchanged)
- `flutter_app/test/phase_c_scoped_backup_test.dart` — including 8 / 64 / 256 MB streaming and Restore / C.1 OOM regression
- `flutter_app/test/phase_c2_backup_storage_search_test.dart` — Downloads hierarchy + user search
- `flutter_app/test/phase_b_network_sync_test.dart`
- `flutter_app/test/eval_backup_assembler_test.dart`

---

## Physical test (required, not performed)

On the non-production tablet only, in-place over 2.7.36 / 2.7.37:

1. Create a backup for a judge who has saved procedure and dilemma lists with attached images/videos.
2. Confirm each list has its own folder under `قوائم التقييم/قوائم تقييم الإجراءات` or `قوائم تقييم المعاضل`, named after the list display name.
3. Confirm that list folder contains its `.xlsx` plus only that list's images/videos.
4. Open an `.xlsx` file and confirm المكتسبة / الملاحظات match the locally saved sheet.
5. Confirm no Information Bank / unit-designation Excel files appear.
6. Confirm restore still uses technical records/`media/`, not edited Excel.

Do **not** install on the production tablet. Do **not** start Phase D.
