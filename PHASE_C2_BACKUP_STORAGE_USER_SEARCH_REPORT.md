# PHASE C.2 — BACKUP STORAGE & USER SEARCH

**Version:** 2.7.36+50  
**applicationId:** `ae.lf.training.lf_training_evaluation`  
**SQLite schema:** 4  
**Date:** 2026-10-17

---

## Summary

Two functional changes only:

1. After a backup is created, hashed, verified, and finalized, it is copied automatically into the Android public Downloads tree. The user is not asked to pick a folder.
2. The Backup & Restore page keeps the existing user Drop-down and adds a name search field directly above it. Search is local/offline UI filtering by display name. Selection identity remains `user_id`.

Phase C.1 bounded-memory backup queries and streaming copy/hash are unchanged. Phase B network/auth/sync is unchanged. No schema change, no migration, no new Flutter/Android dependency.

---

## Automatic Downloads Backup

**PASS**

Verified backup packages are streamed from the private verified folder into:

`Download/SmartArbitration_Backups/<Exercise Display Name>/<Judge Display Name>/Backup_<YYYY-MM-DD_HHmmss>/`

Android 10+ uses MediaStore `Downloads` + `RELATIVE_PATH` (no folder picker, no `MANAGE_EXTERNAL_STORAGE`). Pre-10 uses the public Downloads directory with `WRITE_EXTERNAL_STORAGE` limited to `maxSdkVersion=28`. Copy uses the existing 1 MiB stream buffer. Whole-file `readBytes()` is not used.

Success is reported only after verification **and** public copy complete.

---

## Checklist

Automatic Downloads Backup: **PASS**

Actual Backup Root: `Download/SmartArbitration_Backups`

Directory Structure: `Download/SmartArbitration_Backups/<Exercise Name>/<Judge Name>/Backup_<timestamp>`

Exercise Name Folder: **PASS**

Judge/User Name Folder: **PASS**

Stable exercise_id Preserved: **PASS**

Stable user_id Preserved: **PASS**

Folder Selection Removed: **YES**

Backup Location Visible To User: **PASS**

Success Message Shows Real Location: **PASS**

User Search Added: **PASS**

Search Field Above Drop-down: **PASS**

Existing Drop-down Preserved: **PASS**

Exact Name Search: **PASS**

Partial Name Search: **PASS**

Clear Search Restores List: **PASS**

No-Match Handling: **PASS**

Offline Search: **PASS**

Duplicate Name Handling: **PASS**

Phase C.1 OOM Fix Preserved: **PASS**

Streaming Large Media: **PASS**

Streaming SHA-256: **PASS**

Per-User Isolation: **PASS**

Authentication Secrets Excluded: **PASS**

Local Unsynced Protection: **PASS**

Pending Operations Compatibility: **PASS**

Restore Validation: **PASS**

Database Schema Changed: **NO**

Migration Created: **NO**

New Dependency: **NO**

Phase B Regression: **PASS**

Phase C Regression: **PASS**

APK: `dist/judge-tablet-v2.7.36.apk`

APK Installed: **NO**

Production Tablet Accessed: **NO**

Physical Test Required: **YES**

---

## Change 1 — Public Downloads storage

- Create flow no longer opens `OPEN_DOCUMENT_TREE` / “حفظ النسخة الاحتياطية في الجهاز”.
- Private verified package is still built first (Phase C/C.1 path).
- After `completion_status=verified`, files are streamed into public Downloads.
- Folder names use sanitized **display** names. Arabic is preserved.
- Duplicate display names append `(U{user_id})` only when a collision exists.
- Timestamp folders are local device time: `Backup_2026-10-17_140530`.
- Same-second collision appends `_2`, `_3`, … Never silent overwrite.
- `backup_manifest.json` remains the authoritative identity (`exercise_id`, `user_id`, format, inventory, sizes, SHA-256).
- Success text:

  `تم إنشاء النسخة الاحتياطية بنجاح`

  then `مكان الحفظ:` and the real `Download/SmartArbitration_Backups/...` path.

- Optional `فتح المجلد` uses an existing Android VIEW intent (no new dependency).

Restore still uses the existing SAF folder picker, now initially pointed at Downloads. Restore continues to read and validate `backup_manifest.json`; folder names are not trusted.

## Change 2 — User/judge name search

Layout on «النسخ الاحتياطي والاستعادة» (Device Manager):

```
[ البحث عن المستخدم بالاسم ]
[ قائمة المستخدمين ▼ ]
```

- Empty search: full local provisioned list.
- Partial, trimmed, Latin case-insensitive matching on `display_name`.
- No match: `لا يوجد مستخدم مطابق` (no invalid Drop-down value).
- Clearing search restores the full list.
- Duplicate names remain separate `user_id` options (existing label still shows username / رقم id).
- No network, no new API, no user-record writes.

## Phase C.1 preserved

`createBackupForUser` still uses:

- `backupSelectScopedCacheForUser` (no `SELECT * FROM cache`)
- `backupSelectPendingForUserExercise`
- `backupSelectMediaMetadataForUserExercise`
- per-row / 256 KiB `substr` json_body reads
- `streamCopyFile` / `streamHashFile`
- no in-memory ZIP, no `readAsBytes()`, no `android:largeHeap`

Public copy is an additional streaming pass of the already-verified package.

## Tests

Flutter:

- `flutter_app/test/phase_c2_backup_storage_search_test.dart` — 12 passed (storage hierarchy, Arabic/sanitize/duplicates, search widget + filter, C.1/B surface, restore via manifest).
- `flutter_app/test/phase_c_scoped_backup_test.dart` — 33 passed, including 8 / 64 / 256 MB streaming backups.
- `flutter_app/test/phase_b_network_sync_test.dart` — 12 passed.

Python Phase B:

- `tests/test_tablet_reconnect.py` + `tests/test_eval_judge_attribution.py` — 13 passed.

## Build

- Flavor: tablet
- Signing: unchanged
- applicationId: `ae.lf.training.lf_training_evaluation`
- versionName `2.7.36` / versionCode `50`

## Physical test (required, not performed)

Install **only** on the non-production test tablet, in-place over 2.7.35:

1. Confirm existing local/pending data still present after upgrade.
2. Open النسخ الاحتياطي والاستعادة, confirm search field above Drop-down.
3. Search `أحمد` (or an existing partial name); confirm Drop-down filters; clear search; full list returns.
4. Create backup without picking a folder.
5. Confirm success shows `تم إنشاء النسخة الاحتياطية بنجاح` and the real Downloads path.
6. In ملفاتي → التخزين الداخلي → Download → SmartArbitration_Backups → exercise → judge → `Backup_<timestamp>`, confirm files are visible.
7. Restore from that folder: manifest validation, preview, explicit confirm; unsynced local work still protected.
8. Confirm a large-media backup does not OOM.

Do **not** install on the production tablet. Do **not** start Phase D.
