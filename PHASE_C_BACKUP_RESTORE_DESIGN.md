# PHASE C — SAFE PER-USER BACKUP & RESTORE DESIGN

Pre-implementation review. No source changes are justified until
this document is complete.

**Target version after implementation:** `2.7.34+48`  
**Current verified project version:** `2.7.33+47`  
**applicationId:** `ae.lf.training.lf_training_evaluation`  
**SQLite schema:** `4`

---

## 1. Existing backup mechanisms

| Mechanism | Scope | Container | Memory |
|-----------|--------|-----------|--------|
| `EvalBackupService.createBackup` | Current session user + current exercise | ZIP of Excel + media + `manifest.json` | **UNSAFE:** `readAsBytesSync` of every media file + `ZipEncoder().encode` of the full archive in RAM |
| `EvalBackupService.currentScope` | Authenticated judge only | n/a | Safe (session fields) |
| `OfflineStore.backupSelectPendingForExercise` | user + exercise | SQL/read | **Incomplete:** only `save_results` / results paths |
| `OfflineStore.backupSelectEvalCacheForUser` | `u{userId}:evaluation_*` and `action_eval_*` | SQL/read | **Web path leak:** unscoped `action_eval_*` keys can be included |
| `OfflineStore.backupSelectMediaForExercise` | `exercise_id` + eval item ids | SQL/read | **No `user_id` filter** — other judges’ media on the same exercise can leak |
| Device Admin `/recovery` (`LocalRecoveryService`) | All users / whole tablet | ZIP in RAM | Diagnostic export, not operational restore |

Judge Settings currently opens `/eval-backup` (Excel ZIP). That flow is
not the Phase C operational backup.

## 2. Existing restore mechanisms

There is **no operational restore** of evaluation results / pending work /
media into `tablet_offline.db`.

`LocalRecoveryService` is scan + export only. Device Admin “استعادة
البيانات المحلية” is a read-only recovery viewer. `OfflineStore.clearAll()`
exists for the Device Manager reset control (Requirement 3 — **out of
Phase C scope**) and must not be used by backup or restore.

## 3. Current memory-risk analysis

Confirmed in `eval_backup_service.dart`:

1. Every selected media file is loaded with `File.readAsBytesSync()`.
2. All ZIP members are held as `Map<String, List<int>>`.
3. `ZipEncoder().encode(archive)` builds the complete ZIP as one byte array.
4. The byte array is kept as `zipBytesData` for share/SAF.

A large pending video can therefore imply RAM ≈ file size + ZIP size.
This path **must not** be used for the new backup.

`archive: ^3.6.1` includes `archive_io.ZipFileEncoder` / `InputFileStream`
(same package, not a new dependency). That API streams **writes**. It does
**not** guarantee ZIP64 for files > 4 GiB, and `ZipDecoder.decodeBuffer`
can load entry content during independent validation.

**Decision:** do **not** use ZIP as the portable Phase C package.
Use a **directory package** with streaming file copy. This needs no new
dependency and has no ZIP64 ceiling.

## 4. Current file / storage paths

| Data | Location |
|------|----------|
| SQLite | app databases dir / `tablet_offline.db` (schema v4) |
| Pending media | app documents / `media/pending/{images,videos,files}/` |
| Synced media | app documents / `media/synced/{images,videos,files}/` |
| Judge signatures | app documents / `judge_signatures/` |
| Device id | SharedPreferences `lf_device_id` |
| Reconnect tickets | SharedPreferences `reconnect_ticket_u{id}` |
| Auth salt | SharedPreferences `local_auth_salt_v2` |
| Existing SAF | MethodChannel `lf.training/recovery_export` → `saveZipCopy` (`ACTION_CREATE_DOCUMENT`) |
| Free space | MethodChannel `lf.training/storage` → `getFreeSpace` (`StatFs` on `filesDir`) |

Phase C reuses SAF via a **tree** picker (`ACTION_OPEN_DOCUMENT_TREE`) to
export/import a backup **folder**. Internal work always happens under app
private storage first.

## 5. Proposed backup scope

Identity: **CURRENT EXERCISE + ONE USER**.

- `exercise_id` = Device Sync `device_exercise.id` when present; otherwise
  the authenticated session exercise. Device Manager cannot invent an
  exercise; if none is known, backup is blocked with a clear error.
- `user_id` = authenticated judge for self-backup; explicitly selected
  `local_users.user_id` for Device Manager.

Included (selected user + selected exercise only):

- User-prefixed operational cache (see inventory).
- All `pending_ops` rows with that `user_id` + `exercise_id` (every
  `op_type`, including synced/failed — logical state, unmodified).
- `media_files` owned by that user for that exercise (see isolation).
- Original media bytes referenced by those rows (copy, never move).
- Judge signature PNG for that user if present.
- Exercise display metadata (copy into the package, not a rewrite of
  device-wide cache).
- Safe user identity metadata (no hashes / tickets).

Excluded:

- Other users’ cache / pending / media.
- Entire `cache` table dump.
- `local_users` authentication material.
- `device_meta` (device-wide).
- Library PDFs / Device Sync package blobs.
- SharedPreferences secrets.
- Absolute Android private paths as restore identity.

## 6. User isolation strategy

- Device Manager lists `OfflineStore.allLocalUsers()` and displays only
  `user_id`, `username`, `military_number`, and session display name.
- `password_hash`, `session_json` secrets, cookies, tickets are never
  shown or exported.
- Cache inclusion requires key prefix `u{selectedUserId}:`.
- Pending inclusion requires `user_id == selected`.
- Media inclusion requires `user_id == selected` when the column is set;
  unscoped media (`user_id` null) is included only when it is tied to the
  selected user’s eval item ids **and** the selected exercise (or null
  exercise with those eval ids). Media with another `user_id` is excluded
  even on the same exercise.

Judge self-backup cannot select another user.

## 7. Exercise isolation strategy

- Backup is refused if `exercise_id` is missing/zero.
- Cache detail rows whose JSON contains a different `exercise_id` are
  reported (not silently rewritten) and omitted from the package.
- Pending rows with a different `exercise_id` are omitted.
- Media with a different non-zero `exercise_id` is omitted.
- Restore checks backup `exercise_id` against the tablet’s current
  exercise and **blocks** a mismatch.

## 8. Manifest design

File: `backup_manifest.json`  
Format version: **`backup_format_version = 1`** (independent of APK version).

Minimum fields:

```
backup_format_version
application_id
application_version
application_version_code
schema_version
created_at
exercise_id, exercise_name, exercise_code
user_id, username, military_number, display_name
device_id (non-secret)
record_counts { cache, pending_ops, media_files }
pending_operation_counts_by_status
media_counts, total_media_bytes
file_inventory [ { relative_path, size, sha256, kind } ]
completion_status   // writing | complete | verified | failed
verified_at
```

Completion marker file: `BACKUP_COMPLETE` (written only after content
is on disk). Validation sets `completion_status = verified` in a
post-pass copy of the manifest **inside the package** only after
independent checks pass.

No secrets in the manifest.

Package layout (directory):

```
LF_SCOPED_BACKUP_<exerciseId>_u<userId>_<utcStamp>/
  backup_manifest.json
  BACKUP_COMPLETE
  records/identity.json
  records/exercise.json
  records/cache.json
  records/pending_ops.json
  records/media_files.json
  media/<stableId><safeExt>
  signatures/<userId>.png          (optional)
```

`media_files.json` stores `backup_rel_path`, size, sha256, owner ids,
upload/pending state. Diagnostic `source_local_path` may be recorded
for support but restore **must ignore it**.

## 9. Streaming design

1. Snapshot selected DB/JSON rows into memory maps (small).
2. For each media file: stream-hash the source (`openRead` + SHA-256);
   record size + hash. Do not load the file.
3. Estimate total bytes + 64 MiB overhead; preflight `getFreeSpace`.
4. Write to `*.inprogress/` directory (never the final name).
5. Write JSON records.
6. Stream-copy each media file in ≤ 1 MiB chunks; re-hash destination;
   fail if size/hash diverges from the snapshot (source changed).
7. Write `BACKUP_COMPLETE`.
8. Independently validate the in-progress directory.
9. Rename/commit to the final folder name.
10. Optional SAF tree export: stream-copy the verified folder; validate
    the destination copy.

No `readAsBytesSync` of media. No `ZipEncoder().encode` of the package.
No application-imposed total media size cap.

## 10. Destination / SAF design

- Work directory: app documents `/scoped_backups/`.
- User-accessible copy: reuse MethodChannel family
  `lf.training/recovery_export`:
  - `exportBackupFolder` → `ACTION_OPEN_DOCUMENT_TREE` then streaming
    copy of the verified package.
  - `importBackupFolder` → `ACTION_OPEN_DOCUMENT_TREE` then streaming
    copy into app cache for validate/restore.
- Existing `saveZipCopy` remains for the old Excel export (unused by
  Phase C operational backup).
- No hardcoded development paths. No assumption that raw `Downloads/`
  is writable.

## 11. Validation design

Re-open the **created** package from its destination and verify:

- `backup_manifest.json` exists and parses
- `backup_format_version` is `1`
- `BACKUP_COMPLETE` exists
- `completion_status` is `complete` or `verified`
- required identity/exercise fields present
- inventory matches files on disk
- record counts structurally valid
- every media file exists, size matches, SHA-256 matches
- no `..` path traversal
- no absolute restore paths
- no duplicate conflicting relative paths
- no secret fields in exported JSON

Only then: **BACKUP STATUS = VERIFIED**.

UI statuses (Arabic):

- تم إنشاء النسخة الاحتياطية
- تم إنشاء النسخة الاحتياطية والتحقق منها
- فشل إنشاء النسخة الاحتياطية
- تم إلغاء النسخة الاحتياطية
- النسخة الاحتياطية غير صالحة

## 12. Restore conflict policy

Restore never starts on select. Sequence:

SELECT → READ MANIFEST → VALIDATE → FORMAT → EXERCISE → USER
OWNERSHIP → APP/SCHEMA → PREVIEW → CONFIRM → PRE-RESTORE SNAPSHOT
→ STAGE → VALIDATE STAGED → COMMIT → POST-VERIFY.

Scoped only: selected exercise + selected user. Never
`clearAll()`, never replace `tablet_offline.db`, never replace the
whole `cache` table, never touch other users.

Classification (per cache key / pending id / media id):

| Class | Action |
|-------|--------|
| MISSING LOCALLY | insert |
| SAME | skip |
| BACKUP OLDER (local synced) | keep local |
| BACKUP NEWER (local synced) | apply backup |
| LOCAL UNSYNCED | **BLOCK** |
| CONFLICT | **BLOCK** |

LOCAL UNSYNCED = `locally_modified`, `locally_approved`, or cache
`sync_status` in pending/failed/syncing, or a live pending op for that
item. No “restore anyway” control in Phase C.

## 13. Pending operation policy

**Backup:** copy selected pending rows exactly (including `id` /
`client_op_id`, `op_type`, `sync_status`, attempts, errors). Do not
modify source rows. Do not mark them synced.

**Restore:** insert only if `id` is absent. Existing id → skip
(idempotent, no duplicate). Unknown `op_type` → **do not discard**;
report incompatibility and still keep the row so work is not lost.
Server duplicate submission after restore is prevented by existing
`client_op_id` idempotency on `SyncService.enqueueLocalFirst` /
API `client_op_id`.

## 14. Media restore policy

For each inventory file:

1. Verify backup SHA-256 while streaming.
2. Stream-copy to a staging file under app-private media root.
3. Verify staged SHA-256.
4. If an existing local file has the same hash → reuse; do not
   overwrite a different file silently.
5. Commit rename to the controlled destination; then upsert
   `media_files` with the **new** local path (never the backup
   diagnostic absolute path).

User is not asked to re-pick a restored pending video.

## 15. Rollback strategy

Before mutating restore:

1. Create a scoped streaming safety snapshot of the affected
   user/exercise (same backup engine).
2. Independently verify that snapshot.
3. If snapshot fails → restore does not start.

On failure after mutation:

1. Roll back newly staged media files.
2. Re-apply the safety snapshot with `RestoreMode.rollback`
   (overwrite the keys this restore touched; still never
   `clearAll` and never touch other users).
3. If rollback itself fails → report rollback failure explicitly.

SQLite writes for a restore commit go through a `db.transaction`.

## 16. Sync / restore race prevention

`SyncService` gains a restore hold counter:

- `beginRestoreHold` / `endRestoreHold`
- `flush`, `runFullSync`, and `_onServerBecameReachable` return
  immediately while held

Restore does not mark anything synchronized. After success, Phase B
reconnect/auto-sync may run normally. No sync is started mid-restore.

## 17. Security exclusions

Never exported:

- plaintext passwords
- `password_hash`
- `local_auth_salt_v2`
- judge / device cookies
- HMAC reconnect tickets (`reconnect_ticket`, SharedPreferences keys)
- Device Manager password / hash
- `session_bundle` cache (may contain tickets)
- server session secrets

Identity JSON contains only `user_id`, `username`, `military_number`,
display name.

## 18. Files proposed for modification

**New**

- `flutter_app/lib/services/scoped_backup_models.dart`
- `flutter_app/lib/services/scoped_backup_inventory.dart`
- `flutter_app/lib/services/scoped_backup_io.dart`
- `flutter_app/lib/services/scoped_backup_service.dart`
- `flutter_app/lib/screens/scoped_backup_screen.dart`
- `flutter_app/test/phase_c_scoped_backup_test.dart`
- `PHASE_C_SAFE_BACKUP_RESTORE_REPORT.md` (post-implementation)

**Modify**

- `flutter_app/lib/services/offline_store.dart` — additional **read**
  selectors + restore insert helpers using existing columns; no schema
  change
- `flutter_app/lib/services/sync_service.dart` — restore hold
- `flutter_app/android/.../MainActivity.kt` — folder export/import
- `flutter_app/lib/app.dart` — `/scoped-backup` route + Device Admin allow
- `flutter_app/lib/screens/device_admin_hub_screen.dart` — entry button
- `flutter_app/lib/screens/settings_screen.dart` — judge entry
- `flutter_app/pubspec.yaml` — version `2.7.34+48`
- `flutter_app/lib/theme/device_layout.dart` — default version string
- `BUILD_TABLET.bat` — `2.7.34+48`

**Not modified (intentionally)**

- `EvalBackupService` RAM ZIP (left in place, not used by Phase C)
- `LocalRecoveryService` all-users diagnostic export
- Device Manager reset control (Requirement 3)
- Schema / migrations / `applicationId` / signing / tablet flavor

## 19. DATABASE SCHEMA CHANGE REQUIRED

**NO**

All required fields already exist in schema v4:

- `cache` (`cache_key`, `json_body`, `updated_at`, `sync_status`)
- `pending_ops` (`id`, `user_id`, `exercise_id`, `op_type`, `client_op_id` via `id` / body)
- `media_files` (`id`, `user_id`, `exercise_id`, paths, checksum, sizes, sync_status)
- `local_users` (identity only; hashes never written by this feature)

No new table. No new column. No migration. No second database.

## 20. NEW DEPENDENCY REQUIRED

**NO**

Streaming copy uses `dart:io` `openRead` / `openWrite` and `package:crypto`
(already in `pubspec.yaml`). The directory package needs no ZIP writer.
`archive` stays at `^3.6.1` for the existing Excel export only.

---

**Gate:** schema change = NO, new dependency = NO → implementation may proceed.
