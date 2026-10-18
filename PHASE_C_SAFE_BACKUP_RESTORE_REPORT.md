# PHASE C — SAFE PER-USER BACKUP & RESTORE REPORT

**Version:** 2.7.34+48  
**applicationId:** `ae.lf.training.lf_training_evaluation`  
**Tablet flavor:** `tablet`  
**SQLite schema:** 4  
**Backup format version:** 1  
**Date:** 2026-10-16

---

## 1. Executive Summary

Phase C implements Requirements 4 and 5 only: Device Manager (and the
authenticated judge) can create and restore a **current-exercise /
one-user** operational backup. Large media is copied with bounded
memory. Backup is read-only toward source data. Restore is scoped,
validated, conflict-blocking, and never uses `OfflineStore.clearAll()`
or database-file replacement.

DATABASE SCHEMA CHANGE REQUIRED: **NO**  
NEW DEPENDENCY REQUIRED: **NO**

## 2. Final Backup Architecture

Portable package = **directory**, not a RAM ZIP.

```
LF_SCOPED_BACKUP_<exerciseId>_u<userId>_<utc>/
  backup_manifest.json
  BACKUP_COMPLETE
  records/identity.json
  records/exercise.json
  records/cache.json
  records/pending_ops.json
  records/media_files.json
  media/<id><ext>
  signatures/<userId>.png   (optional)
```

Write path: `*.inprogress/` → validate → commit/rename → re-validate.
User-accessible copy uses existing SAF MethodChannel family with
`ACTION_OPEN_DOCUMENT_TREE` (streaming 1 MiB buffer).

The previous Excel ZIP (`EvalBackupService`) remains in the tree but is
not the Phase C operational backup. Device Admin `/recovery`
all-users diagnostic export is unchanged and separate.

## 3. Per-User Scope

Backup identity is always one `user_id`.

- Judge self-backup: authenticated session user only.
- Device Manager: one selected row from `local_users` (safe fields).

Other users’ cache, pending ops, and media are excluded.

## 4. Current Exercise Scope

`exercise_id` comes from Device Sync `device_exercise` when present,
otherwise the judge session. Backup/restore refuse a missing exercise.
Restore blocks if backup `exercise_id` ≠ current tablet exercise.

## 5. Data Included

- User-prefixed operational cache: evaluation list catalogs/details,
  action/dilemma details, home, incomplete, polarity notes, flow,
  objectives, judge signature.
- All `pending_ops` for that user + exercise (every `op_type`).
- `media_files` owned by that user for that exercise (plus unscoped
  media linked only to that user’s eval ids).
- Original media bytes (copy).
- Signature PNG if present.
- Exercise display metadata and safe user identity.

## 6. Data Excluded

- Other users’ operational data
- Entire `cache` table
- `session_bundle` / `local_auth` / `bootstrap`
- `device_meta`, library PDFs, Device Sync blobs
- SharedPreferences
- Authentication material (see §7)

## 7. Authentication Secret Exclusions

Never exported:

- plaintext passwords, `password_hash`
- `local_auth_salt_v2`
- judge/device cookies
- HMAC reconnect tickets
- Device Manager password/hash
- `reconnect_ticket` inside JSON (stripped if present)

Identity JSON: `user_id`, `username`, `military_number`, display name.

## 8. Streaming / Memory Safety

Media is hashed and copied with `RandomAccessFile.read(chunkSize)` /
`openRead` + `openWrite`. Chunk size default 1 MiB. No
`readAsBytesSync` of media. No `ZipEncoder().encode` of the package.

## 9. Large File Handling

No application total-media-size cap. Preflight uses `getFreeSpace` plus
64 MiB overhead. A source file that changes size/hash during copy fails
the backup; source is left untouched.

## 10. Backup Manifest

`backup_format_version = 1` (independent of APK version). Includes
application id/version/code, schema 4, timestamps, exercise/user
identity, counts, inventory with size + SHA-256, completion status.
No secrets.

## 11. SHA-256 Validation

Independent validation re-opens the created package, checks inventory
membership, size, and SHA-256 of every listed file, plus path-safety.

## 12. Backup Completion / Commit Model

Incomplete packages live only as `*.inprogress`. `BACKUP_COMPLETE` is
written after content. Status becomes **verified** only after
validation of the committed folder.

## 13. Backup Cancellation

Cancel stops creation, deletes only the in-progress output, and leaves
all source data unchanged.

## 14. Restore Validation

Select → read manifest → validate package → format/schema → exercise
match → user match → provisioned user → preview → confirm.

Unsupported format, corrupt manifest, path traversal, and absolute
restore paths are blocked.

## 15. Restore Preview

Preview lists cache/pending/media classifications and blockers before
any mutation.

## 16. Conflict Handling

LOCAL UNSYNCED (`locally_modified`, `locally_approved`, pending/failed/
syncing cache, live pending ops) and CONFLICT **block** restore.
No “restore anyway” control.

## 17. Pending Ops Restore

Rows are copied as-is on backup (including `id` / `client_op_id`).
Restore inserts only if `id` is absent (no duplicate). Unknown
`op_type` is reported and **not** discarded. After restore, existing
API `client_op_id` idempotency prevents duplicate server submission.

## 18. Media Restore

Stream-verify backup SHA-256 → stage under app-private media →
verify staged hash → commit to controlled path → upsert metadata
with the **new** local path. Identical existing hash is reused.
Different existing file is not overwritten silently.

## 19. Pre-Restore Safety Snapshot

A scoped verified backup of the affected user/exercise is created
before mutation. If it cannot be created and verified, restore does
not start.

## 20. Rollback

Failed media/DB apply deletes staged/committed restore files and
re-applies the safety snapshot (`RestoreMode` skip-safety). Rollback
failure is reported explicitly. SQLite writes use `db.transaction`.

## 21. Sync Interaction

`SyncService.beginRestoreHold` / `endRestoreHold` gate `flush`,
`runFullSync`, and `_onServerBecameReachable`. Restore does not mark
records synchronized. Phase B reconnect auto-sync resumes after
restore completes.

## 22. Device Manager Integration

Hub button **النسخ الاحتياطي والاستعادة** → `/scoped-backup` with
user picker. All-users `/recovery` export remains separate. Reset
control (Requirement 3) unchanged.

## 23. Judge Self-Backup

Settings **النسخ الاحتياطي والاستعادة** opens the same screen with
the current user locked.

## 24. Files Modified

New: `scoped_backup_models.dart`, `scoped_backup_inventory.dart`,
`scoped_backup_io.dart`, `scoped_backup_service.dart`,
`scoped_backup_screen.dart`, `test/phase_c_scoped_backup_test.dart`,
this report, `PHASE_C_BACKUP_RESTORE_DESIGN.md`.

Modified: `offline_store.dart` (read selectors + scoped insert helpers,
no schema change), `sync_service.dart` (restore hold),
`MainActivity.kt` (folder SAF), `app.dart`, `device_admin_hub_screen.dart`,
`settings_screen.dart`, `device_layout.dart`, `pubspec.yaml`,
`BUILD_TABLET.bat`.

## 25. Functions Modified

Added store helpers: `localUserById`, `backupSelectPendingForUserExercise`,
`pendingOpById`, `insertPendingIfAbsent`, `cacheRowRaw`, `cacheSetExact`,
`restoreApplyScopedRows`.

`SyncService`: `beginRestoreHold`, `endRestoreHold`, early return in
flush / runFullSync / reconnect / auto full sync.

## 26. Database Impact

Schema version remains **4**. No migration. No new database. No
`clearAll` in backup or restore. Database file is never replaced.

## 27. Dependencies Impact

None. `archive: ^3.6.1` unchanged (Excel export only). Streaming copy
uses `dart:io` + existing `crypto`.

## 28. Automated Tests

`flutter test test/phase_c_scoped_backup_test.dart` — **PASS** (18 tests
covering isolation, secrets, source fingerprints, streaming large file,
cancel, verify, missing/modified media, corrupt/unsupported/path checks,
restore policy, rollback of failed copy, restore-hold, schema/app id).

## 29. Regression Tests

Full `flutter test`: **58 passed**, **1 failed**
(`widget_test.dart` LoginScreen overflow — pre-existing, login screen
not modified in Phase C).

Phase B network/sync tests: **PASS**.

## 30. Physical Tests Required

YES. Test tablet only. Sequence in the Phase C prompt (in-place upgrade
from 2.7.33+47, backup, large video, user isolation, restore). Do not
access the production tablet. Do not `adb install` from this session.

## 31. Known Limitations

- Package is a folder (not a ZIP) so 5 GB media is not limited by ZIP64.
- SAF tree pickers require the user to choose a folder.
- Old Excel RAM ZIP path is unused by the new UI but not deleted.
- Restore of an unprovisioned user is blocked (no invented accounts).

## 32. Final Verdict

Phase C implementation is complete for TEST APK 2.7.34+48.

---

## Mandatory final safety verification

APPLICATION ID: `ae.lf.training.lf_training_evaluation`  
TABLET FLAVOR: `tablet`  
VERSION NAME: `2.7.34`  
VERSION CODE: `48`  
SQLITE SCHEMA: `4`  
DATABASE MIGRATION: NO  
NEW DATABASE: NO  
OfflineStore.clearAll used by backup: NO  
OfflineStore.clearAll used by restore: NO  
Database file replaced by restore: NO  
Source media deleted by backup: NO  
Source media moved by backup: NO  
pending_ops cleared: NO  
media_files cleared: NO  
local_users cleared: NO  
Authentication secrets exported: NO  
Phase B reconnect preserved: YES  
In-place upgrade supported: YES
