# PHASE C.1 — BACKUP OOM FIX

**Version:** 2.7.35+49  
**applicationId:** `ae.lf.training.lf_training_evaluation`  
**SQLite schema:** 4  
**Date:** 2026-10-17

---

## Root Cause

**Exact function:** `OfflineStore.recoverySelectCache()`  
called from `ScopedBackupService.createBackupForUser()`.

**Exact query:** `db.query('cache')` → SQLite `SELECT * FROM cache`  
(all columns, **all users**, all keys).

**Exact field:** `cache.json_body` (TEXT, not a BLOB column).

**File:** `flutter_app/lib/services/offline_store.dart`  
(`recoverySelectCache`, previously invoked at the start of backup).

There is **no SQLite BLOB column** for photos/videos/PDFs. Media lives on
disk under app-private `media/`. Signatures live as PNG files plus a small
`png_b64` TEXT field. The crash was not a video `readAsBytes` on the Dart
isolate.

## Why approximately 59.7 MB was allocated

`createBackupForUser` loaded the **entire** `cache` table (and then the
entire `pending_ops` and `media_files` tables) in one sqflite query so it
could filter in Dart.

sqflite Android encodes the full query result into a single Flutter
platform-channel message. That encoder uses Java
`ByteArrayOutputStream.write` → `ensureCapacity` → `grow` →
`Arrays.copyOf`.

On the test tablet the combined `json_body` TEXT for every cached row
(all judges’ evaluation details, duplicated `library` / `exercise_papers`
payloads, bootstrap/session bundles, home, etc.) required a ~59,719,696
byte buffer. The Dart heap was already ~160/184 MB; the extra ~57 MB
copy on the **Sqflite** thread caused:

`java.lang.OutOfMemoryError`  
`FATAL EXCEPTION: Sqflite`

The previous 8 MB automated test never executed this production query; it
called `writeBackupPackage` with in-memory fixture maps.

## Fix

Bounded-memory backup queries (schema unchanged):

1. **Cache:** `SELECT cache_key, updated_at, sync_status FROM cache WHERE cache_key LIKE 'u{userId}:%'`  
   then `length(json_body)` (integer only)  
   then `json_body` **one key at a time**, or `substr(json_body, ?, ?)` in
   256 KiB chunks streamed to a sidecar file if a single body exceeds 2 MiB.
2. **Pending:** `SELECT id FROM pending_ops WHERE user_id=? AND exercise_id=?`  
   then one row at a time; `body` via chunked `substr` (never the whole table).
3. **Media:** explicit metadata columns only, filtered by `user_id` /
   `exercise_id`. No binary column exists.

Media copy/hash remain `openRead` / chunked SHA-256. Folder package
unchanged. No `android:largeHeap`. No new dependency.

## Google Fonts (read-only audit)

- Invoked in `flutter_app/lib/theme/app_theme.dart`:
  `GoogleFonts.cairo(...)`, `GoogleFonts.cairoTextTheme()`,
  `GoogleFonts.cairo().fontFamily`.
- Cairo is **not** bundled in `pubspec.yaml` assets.
- `google_fonts` fetches TTF from `https://fonts.gstatic.com/...` at
  runtime. Offline, this logs “Failed to load font” and falls back.
- Does **not** cause the Sqflite OOM.
- Future fix (not in this patch): vendor Cairo under `assets/fonts/` and
  use a local `fontFamily` so the app never hits the network for typefaces.

---

## Required status lines

PHASE C.1 — BACKUP OOM FIX

Root Cause:
`OfflineStore.recoverySelectCache()` → `SELECT * FROM cache` (column `json_body` TEXT), invoked by `ScopedBackupService.createBackupForUser`, encoded by sqflite Android `ByteArrayOutputStream` on the Sqflite thread.

Why approximately 59.7 MB was allocated:
The full multi-user cache table TEXT was serialized as one platform-channel result (~59,719,696 bytes), exceeding remaining heap (~160/184 MB, growth limit ~201 MB).

Fix:
Scoped metadata-first SQL; per-key / chunked `substr` reads; explicit media columns; streaming file copy/hash unchanged.

Large SQLite BLOB Selected During Backup Before Fix:
NO (no BLOB column; large TEXT `json_body` selected via `SELECT *`)

Large SQLite BLOB Selected After Fix:
NO

Streaming Media Copy:
PASS

Streaming SHA-256:
PASS

Archive Memory Bounded:
PASS (folder package; no RAM ZIP)

Restore Large-Media Path Audited:
PASS (stream → temp → hash → commit; large cache bodies restore via chunked SQL concat)

Database Schema Changed:
NO

Migration Created:
NO

New Dependency:
NO

Authentication Secrets Still Excluded:
PASS

Per-User Isolation:
PASS

Local Unsynced Protection:
PASS

Pending Operations Compatibility:
PASS

Phase B Regression:
PASS (`test/phase_b_network_sync_test.dart`)

8 MB Test:
PASS

>=64 MB Test:
PASS

>=256 MB Test:
PASS

APK:
dist/judge-tablet-v2.7.35.apk

APK Installed:
NO

Production Tablet Accessed:
NO

Physical Test Required:
YES
