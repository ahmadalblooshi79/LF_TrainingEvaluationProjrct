# PHASE A.1 — APK UPGRADE & LOCAL DATA PRESERVATION SAFETY AUDIT

**Status:** READ-ONLY ANALYSIS COMPLETE  
**Date:** 2026-10-16  
**Inspected app:** `flutter_app/` version `2.7.32+46`  
**Scope:** Can a future APK be installed **in-place** over the currently installed Smart Arbitration tablet app without losing local operational data?

---

## 0. PHASE A.1 SAFETY VERIFICATION

| Check | Result |
|---|---|
| SOURCE FILES MODIFIED | **0** |
| DATABASE FILES MODIFIED | **0** |
| DATABASE SCHEMA MODIFIED | **NO** |
| MIGRATIONS CREATED | **0** |
| APK INSTALLED | **NO** |
| PRODUCTION TABLET ACCESSED | **NO** |
| UI MODIFIED | **NO** |
| DEPENDENCIES CHANGED | **NO** |
| LOCAL DATA MODIFIED | **NO** |
| PENDING OPS MODIFIED | **NO** |
| MEDIA MODIFIED | **NO** |
| USERS MODIFIED | **NO** |

This document is analysis only. No APK was installed. No production tablet was accessed.

---

## 1. Executive Summary

**Android in-place upgrade can preserve the app sandbox** when all of the following are true:

1. Future APK uses the **same** `applicationId`: `ae.lf.training.lf_training_evaluation`
2. Future APK is the **tablet** flavor (not `phone`)
3. Future APK is signed with the **same** certificate as the installed APK
4. Future `versionCode` is **greater than** the installed `versionCode` (currently **46**)
5. Future code **does not** bump SQLite schema past 4 with a destructive migration
6. Future code **does not** call `OfflineStore.clearAll()` on startup
7. The operator uses **update install** (`adb install -r` / system “update app”), **never uninstall**, **never Clear Data**

Under those conditions, `tablet_offline.db`, `pending_ops`, `media_files`, `local_users`, cache JSON, app-private photos/videos/PDFs, SharedPreferences (including offline salt), and cookie directories **survive because Android keeps `/data/data/<applicationId>/`**.

Startup of version 2.7.32+46 **does not** wipe that sandbox. `openDatabase(version: 4)` on an existing v4 file does **not** run `onCreate` or `onUpgrade`.

**This is not “100% safe” from source inspection alone.**

Two production gates are **not closed from the repository**:

1. **Signing continuity is NOT CONFIRMED FROM SOURCE CODE ALONE.** Release builds are signed with the **debug** keystore. That key is machine-local, gitignored, and not identified as a production release key.
2. **FULL VERIFIED PRE-UPDATE BACKUP NOT CURRENTLY AVAILABLE** for large media (ZIP is encoded in RAM).

**Final verdict:** CONDITIONALLY SAFE — BLOCKERS MUST BE RESOLVED (see §23–§24).  
A physical **non-production** in-place upgrade test is mandatory before the important tablet.

---

## 2. Android Application Identity

| Field | Exact value | Source |
|---|---|---|
| `applicationId` (tablet) | `ae.lf.training.lf_training_evaluation` | `flutter_app/android/app/build.gradle.kts` `defaultConfig` |
| `namespace` | `ae.lf.training.lf_training_evaluation` | same file |
| Package / MainActivity | `ae.lf.training.lf_training_evaluation.MainActivity` | `MainActivity.kt` |
| Display name | `التحكيم الذكي` | `res/values/strings.xml` |
| `versionName` | `2.7.32` | `flutter_app/pubspec.yaml` `version: 2.7.32+46` → Gradle `flutter.versionName` |
| `versionCode` | `46` | pubspec `+46` → Gradle `flutter.versionCode`; `BUILD_TABLET.bat` `--build-number=46` |
| Flavor dimension | `device` | `build.gradle.kts` |
| Flavor `tablet` | **no** `applicationIdSuffix` | same as defaultConfig |
| Flavor `phone` | `applicationIdSuffix = ".phone"` | **different app:** `ae.lf.training.lf_training_evaluation.phone` |
| Other app in repo | `com.lf.systemtablet` | `system_tablet/` — **not** this product |

**SAME applicationId → Android may perform an in-place upgrade.**  
`BUILD_TABLET.bat` builds `--flavor tablet` and echoes `Package: ae.lf.training.lf_training_evaluation`.

**DIFFERENT applicationId → Android treats it as a different app (empty sandbox).**  
Forbidden for this tablet:

- `BUILD_PHONE.bat` / `--flavor phone`
- Installing `system_tablet` (`com.lf.systemtablet`)
- Changing `applicationId` in Gradle (do not change it)

No `applicationId` change is recommended or required for Phases B–F.

---

## 3. APK Signing Configuration

Inspected:

- `flutter_app/android/app/build.gradle.kts` `buildTypes.release`
- `flutter_app/android/.gitignore` (`key.properties`, `*.keystore`, `*.jks`)
- Repository: **no** `key.properties`, **no** `.jks` / `.keystore` files

Current release signing (verbatim intent in Gradle):

```
// TODO: Add your own signing config for the release build.
// Signing with the debug keys for now, so `flutter run --release` works.
signingConfig = signingConfigs.getByName("debug")
```

| Question | Finding |
|---|---|
| Is a release keystore configured? | **No** |
| `signingConfigs.release` used? | **No** |
| `key.properties` used? | **No** (gitignored placeholder only) |
| Environment-based signing? | **No** |
| Debug signing used for release? | **Yes — CONFIRMED** |
| Can future builds use the same key? | Only if built on a machine that still has the **same** `debug.keystore` that signed the installed APK |

Android debug keystores are **per-developer-machine**. Alias/password defaults are well-known; the **certificate is unique per generated keystore**.

**SIGNING CONTINUITY:** **NOT CONFIRMED FROM SOURCE CODE ALONE**  
Also: **AT RISK** if production was built on another PC, or if a future change introduces a real release keystore.

### Safe non-destructive certificate comparison (do later — do not install)

Do **not** print private keys or passwords.

1. On the **new APK file** (workstation):  
   `apksigner verify --print-certs path\to\new.apk`  
   or `keytool -printcert -jarfile path\to\new.apk`  
   Record SHA-256 of the signing certificate.
2. On a **non-production** tablet that already has the app, or via a copy of the currently installed APK pulled without uninstall:  
   `adb shell dumpsys package ae.lf.training.lf_training_evaluation`  
   and compare `signing` / `signatures` SHA-256  
   or pull the installed APK with `adb shell pm path …` then `adb pull` and print certs the same way.
3. Match → Gate 2 PASS. Mismatch → **PRODUCTION UPDATE BLOCKED** (`INSTALL_FAILED_UPDATE_INCOMPATIBLE`). Uninstall would “fix” it and **destroy all local data** — forbidden.

**Do not switch to a new official release keystore** until a migration plan exists. Switching keys **requires uninstall** on current debug-signed devices.

---

## 4. VersionCode / VersionName Rules

| Item | Current | Where to change later (not now) |
|---|---|---|
| `versionName` | `2.7.32` | `flutter_app/pubspec.yaml` `version:` **and** `BUILD_TABLET.bat` `--build-name=` / `LF_APP_VERSION` |
| `versionCode` | `46` | pubspec `+N` **and** `BUILD_TABLET.bat` `--build-number=` |

Gradle: `versionCode = flutter.versionCode`, `versionName = flutter.versionName` from Flutter.

Future APKs **must**:

- Same `applicationId`
- Same compatible signing identity
- **Higher** `versionCode` than installed (next tablet build ≥ **47**)

Equal `versionCode` → Android may refuse the update (`INSTALL_FAILED_VERSION_DOWNGRADE` / already installed). Lower is refused.

Scripts that can **accidentally** change identity:

| Script | Effect |
|---|---|
| `BUILD_TABLET.bat` | Correct package; currently pins 2.7.32+46 |
| `BUILD_PHONE.bat` | **Different applicationId** — must never be installed on the production tablet |
| `BUILD_PWA.bat` | Web only; does not install Android |
| Gradle `productFlavors.phone` | Suffix `.phone` |
| `signingConfig = debug` | Identity of **key**, not package |

No repository script runs `adb uninstall` or `pm clear` (see §16).

---

## 5. Database Preservation Analysis

| Item | Value |
|---|---|
| Filename | `tablet_offline.db` |
| Path logic | `p.join(await getDatabasesPath(), 'tablet_offline.db')` |
| Typical Android path | `/data/data/ae.lf.training.lf_training_evaluation/databases/tablet_offline.db` |
| Technology | sqflite |
| Schema constant | `OfflineStore.databaseSchemaVersion = 4` |
| `openDatabase` version | `4` |
| `onDowngrade` | **Not defined** |
| `deleteDatabase` | **Not present** in `flutter_app/` |
| `DROP TABLE` | **Not present** in `flutter_app/` |

In-place APK update **does not move or delete** this file. UID and package directory stay the same.

Opening an **existing** v4 database with version 4:

- `onCreate` **does not run**
- `onUpgrade` **does not run**
- No row mutation from open itself (sqflite open is not a data rewrite)

---

## 6. Database onCreate / onUpgrade / onDowngrade Analysis

File: `flutter_app/lib/services/offline_store.dart`  
Class: `OfflineStore`  
Init: `init()` → `_database` → `openDatabase`

```
APP START
  main() → OfflineStore.init()
    native: await _database
      getDatabasesPath() + tablet_offline.db
      openDatabase(path, version: 4,
        onCreate: _createV2 + _upgradeToV3 + _upgradeToV4
        onUpgrade: if old<2 _upgradeToV2; if old<3 _upgradeToV3; if old<4 _upgradeToV4
      )
```

### onCreate (empty device only)

Runs **only if the file does not exist**. Not used on APK upgrade of an already-initialized tablet.

Creates: `cache`, `pending_ops`, `media_files`, then v3 `local_users` + `device_meta`, then v4 `ALTER TABLE media_files ADD COLUMN …`.

### onUpgrade (only if stored user_version < 4)

| From | Action | Destructive? |
|---|---|---|
| <2 | `_upgradeToV2`: `ALTER TABLE` add columns; `CREATE TABLE IF NOT EXISTS media_files` | **No** (ALTER / IF NOT EXISTS). Errors swallowed. |
| <3 | `_upgradeToV3`: `CREATE TABLE IF NOT EXISTS local_users`, `device_meta` | **No** |
| <4 | `_upgradeToV4`: `ALTER TABLE media_files ADD COLUMN` (client_uuid, user_id, checksum, upload_session_id, …) | **No** — additive only; `catch (_)` if column exists |

**CONFIRMED:** current migrations do **not** `DROP TABLE`, do **not** `DELETE FROM` during upgrade, do **not** delete the DB file.

### onDowngrade

**Absent.** Shipping a future APK with SQLite version **&lt; 4** against a v4 file will throw on open and **crash startup**. Data file remains, but the app will not start. **Do not decrease schema version.**

### Destructive search classification (`flutter_app/`)

| Pattern | Occurrences that matter | Classification |
|---|---|---|
| `deleteDatabase` | none | — |
| `DROP TABLE` / `DROP DATABASE` | none | — |
| `onUpgrade` / `onCreate` | additive schema only | **non-destructive** |
| `onDowngrade` | none | crash if version lowered; no wipe |
| `db.delete('cache'/'pending_ops'/…)` | `clearAll()` | **DESTRUCTIVE** — Device Manager reset only |
| `db.delete('media_files')` | `clearAll`; `deleteMediaRecord` (user removes one criterion file) | not startup |
| `DELETE FROM` SQL string | none (sqflite `.delete`) | see `clearAll` |
| `File(...).delete` | `markMediaSynced` (moves pending→synced); `deleteSyncedMediaFiles`; `removeLastCriterionMedia`; PDF prune | not APK upgrade; not startup |
| `clearAll` | `OfflineStore.clearAll` → Device Admin `_resetDevice` | **FORBIDDEN as repair**; not called from `main()` |
| `LibraryPdfCache.clearAll` | only from `clearAll()` | reset only |
| `pruneLibraryPdfsExcept` | after **successful** library+papers prefetch | network path, not upgrade |
| PWA IndexedDB `clear` | web only | not Android APK |

**Migration failure:** failed `ALTER` is ignored (`catch`). Open does not recreate the database. Exceptions in `openDatabase` would fail `init()` and stop `main()` — **files remain**.

**Does upgrade preserve tables?** Yes, for v2→v4 additive path: `pending_ops`, `media_files`, `local_users`, `cache` are kept. Current production is already v4, so **no upgrade callback runs**.

---

## 7. Startup Data Safety

`main()` order (`flutter_app/lib/main.dart`):

1. `OfflineStore.instance.init()` — open DB
2. `ApiClient.instance.init()` — read `server_base_url`, open cookie jars
3. `ConnectivityService.instance.init()`
4. `SyncPreferences.instance.init()` — read mode, default **manual**
5. `DeviceAdminService.instance.init()` — `ensureDefaultAdmin()` then read `device_ready`
6. `DevicePresenceService.instance.init()` — create device id **only if missing**
7. `AuthService.instance.prepareLocalAuth()` — **clears in-memory session only**; does not delete `local_users`
8. Background: `HealthService.start`, `SyncService.start`, notifications, presence

| Risk | Startup of 2.7.32+46 |
|---|---|
| Clear cache | **No** |
| Delete pending_ops | **No** |
| Delete media / users | **No** |
| Reset device_meta | **No** (`ensureDefaultAdmin` writes prefs only if hash/user empty or legacy `device_admin`) |
| Recreate database | **No** |
| Automatic sync | **Only if** `tablet_sync_mode == automatic` **and** user is logged in **and** LAN + health OK. After APK update, process is new: `isLoggedIn` is false until the judge logs in again. |
| Automatic download replacing local | After **online** login, `LoginScreen` calls `prefetchForOffline` (skipped if `lastLoginWasOffline`). Prefetch uses `mergeServerCacheWithLocal` when `locally_modified` / pending. |
| `clearAll` | **Not on startup** |

`prepareLocalAuth` comment: reads local credentials **without** opening a session. User must log in again after any process death, including APK update. **Offline hashes remain.**

**CRITICAL operational rule for the first launch after upgrade:** keep Ethernet disconnected until local counts/IDs are verified. Then, if sync mode is automatic, login+network can flush pending and download. That is not a wipe, but Gate 15 requires local proof **before** sync.

`DeviceAdminService.ensureDefaultAdmin`: if `device_admin_username` + hash already exist and user is not legacy `device_admin`, it **returns without writing**. Salt-stable hashes remain valid.

---

## 8. SharedPreferences Preservation

Android location: app sandbox `shared_prefs` (Flutter plugin). **Survives in-place APK update.** Lost on uninstall / Clear Data.

| Key | Purpose | Startup reset? | Logout? | Device reset (`clearAll` native)? |
|---|---|---|---|---|
| `server_base_url` | Server URL | No (may normalize digits/port) | No | **No** (native clearAll does not wipe prefs) |
| `local_auth_salt_v2` | Offline password salt | Created only if empty | No | **No** |
| `device_admin_username` | Device Manager user | Only if missing/legacy | Device admin logout is in-memory | **No** |
| `device_admin_password_hash` | Device Manager hash | Same | No | **No** |
| `tablet_sync_mode` | automatic / manual | No | No | **No** |
| `was_logged_in` | UX flag | No | Set **false** | **No** |
| `last_sync_at` | Last successful sync | No | No | **No** |
| `lf_device_id` / `lf_device_name` | Presence | Generated if empty | No | **No** |

Device-ready flags live in SQLite `device_meta`, not prefs (`device_ready`, `last_package_at`).

**Do not rename** `local_auth_salt_v2`. A new salt with old `local_users.password_hash` would make **all offline logins fail** without deleting rows.

Native `clearAll` does **not** remove SharedPreferences. Web `clearAll` removes only migratable PWA keys.

---

## 9. Cookie / Session Preservation

| Jar | Path | Created by |
|---|---|---|
| Judge | `{getApplicationDocumentsDirectory()}/.cookies_judge` | `api_client_io.createCookieJar(name: 'judge')` |
| Device | `{...}/.cookies_device` | `name: 'device'` |

Typical Android documents root: `/data/data/ae.lf.training.lf_training_evaluation/app_flutter/`

`PersistCookieJar` + `FileStorage`. `ignoreExpires: false`.

| Event | Cookies |
|---|---|
| In-place APK update | **Files remain** (same documents dir) |
| Uninstall / Clear Data | **Deleted** |
| `AuthService.logout` | `ApiClient.clearCookies()` → `deleteAll()` on judge jar |
| `refreshFromServer` 401 | `clearCookies()`; **local session kept** |
| `setBaseUrl` | Does **not** delete jars |
| `OfflineStore.clearAll` | Does **not** delete cookie files |
| Startup `ApiClient.init` | Reopens jars from disk; no wipe |

Expired cookies after upgrade: health ping may succeed; authenticated APIs 401. **Local judge data must remain** — current 401 path clears cookies only, not SQLite. Phase B silent re-auth must keep that rule.

In-memory `AuthService._session` is **not** restored at boot. That is session UX, not data loss.

---

## 10. Local User / Offline Login Preservation

| Store | Contents |
|---|---|
| `local_users` | `user_id`, `username`, `military_number`, `password_hash`, `session_json`, `updated_at` |
| Cache `local_auth` / `session_bundle` | Legacy single-judge fallback |
| Pref `local_auth_salt_v2` | Salt for `credentialDigest` (`lf.v2\|salt\|username\|password` SHA-256) |
| `_legacyCredentialDigest` | v1 fallback; upgrades hash on successful match |

In-place update preserves `local_users` + salt → **provisioned judges can still log in offline**, provided:

- Salt key/algorithm unchanged
- `credentialDigest` material string unchanged
- `ensureDefaultAdmin` does not rotate salt (it does not)

`prepareLocalAuth` does not delete users.

**Phase B risk:** silent re-auth must **not** regenerate salt or rewrite all hashes. Plaintext passwords are not stored.

---

## 11. Cache Backward Compatibility

Cache is JSON in `cache.json_body` keyed by `u{userId}:{logicalKey}` (and some unscoped keys).

Known logical keys include: `home`, `evaluation_lists::`, `evaluation_lists:{unit}:{phase}`, `evaluation_list_detail:…`, `action_eval_lists:`, `action_eval_lists:{day}`, `action_eval_detail:{slot}`, `flow:`, `objectives`, `incomplete`, `exercise_details`, `library`, `exercise_papers`, `session_bundle`, `judge_signature`, `polarity_notes`.

Judge-work fields (must remain readable):

`locally_modified`, `locally_approved`, `saved_payload`, `saved_rows`, `local_media`, `workflow`, `status_label`, `dispatch_label`, `approval_signature`, `is_approved`, `can_edit`, `can_approve`

Parsers (`EvalRow.fromJson`, `EvalSheet` factories, `PendingOp.fromRow`) use optional casts and defaults. **Extra JSON fields are ignored.**

Phase E may **write** additional status fields; it must **not** require new required keys that make old sheets fail to parse.

`mergeServerCacheWithLocal` keeps local `saved_payload` / `saved_rows` / `local_media` / approval signature when local work exists.

---

## 12. Pending Operations Backward Compatibility

Table `pending_ops` (v2+ columns already present on schema 4):

`id` (client_op_id / PK), `method`, `path`, `body` (JSON text), `kind`, `op_type`, `created_at`, `attempts`, `last_error`, `sync_status`, `judge_id`, `user_id`, `exercise_id`, `list_id`, `eval_item_id`, `media_local_path`

`PendingOp.fromRow` defaults missing strings (`op_type` → `unknown`, `method` → `POST`).

Current `opType` values: `save_results`, `approve`, `media_upload`, `polarity_notes_bulk`, `polarity_note_save`, `polarity_note_delete`, `save_signature`.

`SyncService.flush` sends by **stored HTTP method + path + body**, with `idempotencyKey: op.id`. Unknown `opType` still uploads unless it is `media_upload` (special chunked path).

**Required principle:** an op created on 2.7.32+46 must still flush after upgrade.

Phase B **must not**:

- Rename/remove columns without additive ALTER
- Change existing API paths that old `path` values point to
- Silently `removeOp` on parse failure
- Filter out unknown `opType`

`removeOp` today: successful HTTP, or user `removeLastCriterionMedia`. **Not on startup.**

---

## 13. Media Queue Backward Compatibility

`media_files` v4 columns include `local_path`, `sync_status`, `client_uuid`, `checksum`, `upload_session_id`, `uploaded_bytes`, `file_size`, sheet FKs.

Queue path:

```
OLD VERSION queued video
  persistMediaFile → app_flutter/media/pending/videos/{opId}{ext}
  upsertMedia + pending_ops opType=media_upload
APK UPDATE (same applicationId)
  same absolute path under /data/data/<id>/app_flutter/...
NEW VERSION
  MediaUploadService.uploadOne(File(rec.localPath))
  if file missing → error, record kept
  if upload_session_id set → resume via /media/upload/status
  else init new chunked session with same client_uuid
```

Judge does **not** need to re-pick the file if `local_path` still exists.

Phase B large-file work must keep `uploadOne` reading **existing** rows and files. Do not require new mandatory columns that old rows lack (`fromRow` already defaults numeric/optional fields).

---

## 14. Photos / Videos / PDFs Storage Analysis

All of these live in **app-private storage**, not public Downloads (except user-chosen SAF ZIP copies).

| Category | Storage location | Ownership | DB reference | In-place APK update | Uninstall | Clear Data |
|---|---|---|---|---|---|---|
| SQLite | `…/databases/tablet_offline.db` | app | — | **YES** | NO | NO |
| Photos/videos pending | `{docs}/media/pending/images\|videos\|files/` | app | `media_files.local_path`, `pending_ops.media_local_path` | **YES** | NO | NO |
| Photos/videos after sync | `{docs}/media/synced/…` (file moved; record kept) | app | `media_files` | **YES** | NO | NO |
| Signatures | `{docs}/judge_signatures/u{userId}.png` + cache `judge_signature` | app | cache | **YES** | NO | NO |
| Library PDFs | `{docs}/library_pdfs/{nodeId}.pdf` | app | not SQL; file cache | **YES** | NO | NO |
| Flow-day PDFs | `{docs}/flow_day_pdfs/{safeName}.pdf` | app | file cache | **YES** | NO | NO |
| Eval backup ZIP | `{docs}/eval_backup/` | app | none | **YES** | NO | NO |
| Cookies | `{docs}/.cookies_judge` / `.cookies_device` | app | none | **YES** | NO | NO |
| SAF copy in Downloads | user-chosen Documents URI | user | none | **YES** (outside sandbox) | **YES** | **YES** |

`persistMediaFile` copies into app private storage immediately (not a transient `content://` URI). That is why queued media survives process death **and** in-place upgrade.

Cleanup that can remove files (**not** APK upgrade, **not** `main()`):

- `deleteSyncedMediaFiles` — Device Manager “Delete Synced Media” (synced only)
- `removeLastCriterionMedia` — judge deletes last criterion file
- `markMediaSynced` — deletes **pending** copy after copy to `synced`
- `LibraryPdfCache.pruneExcept` — after full library+papers prefetch
- `clearAll` — Device reset

Pending (unsynced) media is **not** targeted by `deleteSyncedMediaFiles`.

---

## 15. APK Update vs Uninstall Analysis

| Path | Android effect | Allowed for production tablet? |
|---|---|---|
| **A.** `adb install -r` / Play-style update / “Install” over same package+cert+higher versionCode | Replaces APK; **keeps** `/data/data/<id>/` | **ONLY acceptable path** |
| **B.** Uninstall then install | **Deletes entire sandbox** (DB, media, prefs, cookies) | **FORBIDDEN** |
| **C.** Settings → Clear storage / Clear data / `pm clear` | Same as data wipe, app remains | **FORBIDDEN** |
| `OfflineStore.clearAll()` | Wipes SQL + PDF cache; not Android uninstall | **FORBIDDEN as repair** |

`android:allowBackup="true"`: Google Auto Backup is **not** a trustworthy operational backup. It does not replace in-place update. Do not uninstall expecting cloud restore.

---

## 16. Deployment Script Safety

Searched: `adb uninstall`, `pm uninstall`, `pm clear`, `adb install`, `flutter install`, `install -r` in `*.bat`, `*.ps1`, `*.sh`, `*.py`, `*.md`.

| Finding | Notes |
|---|---|
| **No** `adb uninstall` / `pm uninstall` / `pm clear` in this repo | Good |
| **No** `adb install` / `flutter install` in build scripts | `BUILD_TABLET.bat` only **builds and copies** to `dist\judge-tablet-v2.7.32.apk` |
| `BUILD_PHONE.bat` | Different `applicationId` — must not be used on this tablet |
| Gradle `clean` | Deletes **build** directory, not device data |
| `pip install -r` | Python venv only |

Operators must not invent an uninstall step. Documented future install: `adb install -r dist\judge-tablet-vX.Y.Z.apk` **after** gates pass, **on TEST TABLET first**.

---

## 17. Phase B–F Data Risk Matrix

| Phase | DB Schema | Existing DB Rows | pending_ops | media_files | local_users | Cache | Risk |
|------|-----------|------------------|-------------|-------------|-------------|-------|------|
| **B** Network/session + media + Device Sync | **NO** if silent re-auth uses cookies/login API only. **POSSIBLY** only if a stored refresh token is invented | Must not DELETE. Reconnect must not `clearAll` | Must keep old rows; do not change `path`/`id`. 401 must not `removeOp` | Keep `local_path` + chunk resume | Must not rewrite hashes/salt | Prefetch/updateMyData must keep `mergeServerCacheWithLocal` | **CRITICAL** (session + upload) |
| **C** Backup/restore | **NO** | Read-only export preferred. Restore-into-DB is high risk if ever added | Export only; do not delete after export | Stream files; do not delete sources | Read-only | Read-only | **HIGH** (OOM / bad restore) |
| **D** Device Manager lists/downloads/reset widget | **NO** | Viewer must be read-only except explicit return-list | Return-list may enqueue ops — must be intentional | Downloads copy, do not delete pending | Iterate `local_users`, do not delete | Read `cacheGetForUser` | **HIGH** (wrong user / reopen) |
| **E** Status + progress | **NO** | May UPDATE cache JSON status fields; must not delete sheets | Old save/approve ops still valid | No | No | Additive status fields; keep `locally_*` | **HIGH** (wrong status) |
| **F** UI / navigation | **NO** | No | No | No | No | Must reuse same keys/routes | **MEDIUM** (nav only) |

Safeguards before any phase:

- Keep schema version **4** unless a later audit proves otherwise
- Never call `clearAll` except the existing Device reset control
- Never solve bugs by deleting DB/prefs
- Keep `mergeServerCacheWithLocal`
- Keep `client_op_id` = `pending_ops.id`
- Test in-place upgrade on TEST TABLET with unsynced data before production

---

## 18. Database Migration Decision

**DATABASE SCHEMA CHANGE REQUIRED: NO**

Re-verified for B–F:

- B: cookies, health, flush lock, timeouts — no new table required. Silent re-auth **POSSIBLY** wants a refresh token; that can be SharedPreferences or reuse device-setup session — **not** an evaluation-schema change. Do not design it in A.1.
- C–F: files, JSON fields, UI, permissions — existing tables suffice.

If a future engineer proposes bumping `openDatabase(version:)`:

**STOP.** Additive `ALTER TABLE` only, with `CREATE TABLE IF NOT EXISTS` / `ADD COLUMN`, never DROP/DELETE. Physical test on a copy of production-like data first.

---

## 19. Production Update Safety Gates

Before **any** APK is allowed onto the important production tablet:

| Gate | Requirement | Fail → |
|---|---|---|
| 1 | New APK `applicationId` == `ae.lf.training.lf_training_evaluation` (tablet flavor, no `.phone`) | BLOCKED |
| 2 | Signing cert SHA-256 matches installed package | BLOCKED |
| 3 | New `versionCode` > installed (installed expected 46 unless already newer) | BLOCKED |
| 4 | SQLite version still 4 **or** proven additive onUpgrade only; no DROP/DELETE | BLOCKED |
| 5 | `main()` still does not call `clearAll` / `deleteDatabase` | BLOCKED |
| 6 | No startup deletion of `pending_ops` | BLOCKED |
| 7 | No startup deletion of `media_files` or pending files | BLOCKED |
| 8 | No startup deletion of `local_users` / salt key rename | BLOCKED |
| 9 | No startup `DELETE FROM cache` | BLOCKED |
| 10 | Old cached sheets still parse | BLOCKED |
| 11 | Old `PendingOp.fromRow` still works | BLOCKED |
| 12 | Old `media_files.local_path` still uploadable via `uploadOne` | BLOCKED |
| 13 | Upgrade tested on **NON-PRODUCTION** tablet first | BLOCKED |
| 14 | Test tablet had simulated **unsynchronized** scores, notes, photo, large video | BLOCKED |
| 15 | After upgrade, local verification **before** Ethernet/sync | BLOCKED |

**If any gate fails: PRODUCTION APK UPDATE = BLOCKED.**

---

## 20. Pre-Update Backup / Snapshot Assessment

Current in-app tools:

| Tool | What it covers | Mutates tablet? | Trustworthy for large media? |
|---|---|---|---|
| `LocalRecoveryService` ZIP | Scans pending_ops + cache + media paths | Export can copy via SAF; scan is read-only | **NO** — full ZIP in RAM (`ZipEncoder.encode`) |
| `EvalBackupService` | Current logged-in user + current exercise xlsx+media | Writes `{docs}/eval_backup/` then share | **NO** for large videos — RAM ZIP |
| Device reset | — | **Destructive** | Forbidden |
| Android Auto Backup | Uncontrolled cloud | Uninstall/reinstall only | **NO** for operations |

**FULL VERIFIED PRE-UPDATE BACKUP NOT CURRENTLY AVAILABLE**

Must be preserved independently (future method — **do not build in A.1**):

1. Copy `tablet_offline.db` (and `-wal`/`-shm` if present) while app is **fully stopped**
2. Copy `app_flutter/` tree (`media/`, `library_pdfs/`, `flow_day_pdfs/`, `judge_signatures/`, `.cookies_*`, `eval_backup/`)
3. Copy `shared_prefs`
4. Record row counts and `pending_ops.id` list, `media_files.id` + file SHA-256

Safe **non-mutating** options later:

- `adb backup` is deprecated/unreliable
- `adb pull` of `/data/data/...` usually needs **root** or backup/debuggable
- Device Manager recovery ZIP is the only in-app export, but **cannot be trusted for very large video sets** (Phase A RAM finding)

Until a streaming copy exists, the **primary preservation mechanism is in-place update itself** plus a TEST TABLET rehearsal — not a full production snapshot.

---

## 21. Non-Production Upgrade Acceptance Test

**TEST TABLET only. PHYSICAL ANDROID TABLET.**

### BEFORE upgrade — seed

- Device Sync already provisioned at least one judge
- Offline login works (Ethernet unplugged)
- One evaluation list with saved scores + notes + signature
- One pending save (`pending_ops` `save_results`)
- One pending approval if the sheet allows
- One photo + one large video queued (`media_files` pending, files on disk)
- Cached library PDF
- Exercise details present

### BEFORE — record (do not skip)

- Installed `versionName` / `versionCode` (`dumpsys package`)
- Signing SHA-256
- `tablet_offline.db` exists
- Counts: `cache`, `pending_ops`, `media_files`, `local_users`, `device_meta`
- All `pending_ops.id`
- All `media_files.id` + `local_path` + SHA-256 of files
- Important cache keys (home, list details with `locally_modified`)
- `local_users.user_id` / usernames (not password hashes in the report)
- `local_auth_salt_v2` **present** (not the value in tickets)

### INSTALL

```
adb install -r <new-tablet-apk>
```

**NO uninstall. NO Clear Data. Ethernet unplugged.**

### AFTER — local only, before server

- Same package, higher versionCode
- Same DB file
- Same row counts (±0 for those tables)
- Same pending IDs
- Same media IDs, paths exist, hashes match
- Same local_users
- Offline login succeeds
- Open sheet: same scores, notes, signature
- PDFs still open

### ONLY THEN — Ethernet

- Old pending ops upload (idempotent `client_op_id`)
- Old queued media continues (no re-pick)
- No duplicate lists
- No lost scores
- Local unsynced still wins if download occurs (`mergeServerCacheWithLocal`)

Fail any local check → **do not** connect that device to the server; **do not** touch production.

---

## 22. Physical Tablet Tests Required

| Device class | Role |
|---|---|
| **TEST TABLET** | First in-place upgrade; unsynced data; signing comparison; Ethernet reconnect later |
| **PRODUCTION DATA TABLET** | Important operational data. **Not** first install target for B–F APKs |

Required progression:

```
SOURCE CODE TESTS
  → TEST APK (tablet flavor, versionCode > 46, same cert)
  → NON-PRODUCTION TABLET
  → IN-PLACE UPGRADE WITH UNSYNCED DATA
  → LOCAL DATA VERIFICATION (Ethernet off)
  → NETWORK / SYNC VERIFICATION
  → APPROVAL
  → PRODUCTION DATA TABLET (same install -r method)
```

PWA / emulator **cannot** prove APK sandbox preservation.

---

## 23. Blocking Issues

Production in-place update is **BLOCKED** until these are closed:

1. **Signing continuity not established from source.** Release uses debug key; production cert not proven to match this builder’s `debug.keystore`. Compare SHA-256 (Gate 2).
2. **Introducing a new release keystore later would block in-place update** of currently debug-signed tablets (would require uninstall — forbidden). Stay on the **same** key as the installed app.
3. **FULL VERIFIED PRE-UPDATE BACKUP NOT CURRENTLY AVAILABLE** for large media.
4. **Must not install phone flavor or `system_tablet`.**
5. **Must increment `versionCode` above installed value.**
6. **Physical TEST TABLET rehearsal not yet done** (mandatory Gate 13).
7. **First launch after upgrade must not auto-sync before local verification** if `tablet_sync_mode` is `automatic` — unplug Ethernet / do not log in online until counts match.

**Not blockers (code audit of 2.7.32+46):**

- `applicationId` for tablet flavor is stable
- No uninstall in scripts
- Schema v4 open is non-destructive
- `main()` does not wipe data
- pending_ops / media_files / local_users formats are readable by current code
- Queued media uses app-private absolute paths

---

## 24. Final Data Preservation Verdict

**B. IN-PLACE APK UPDATE DATA PRESERVATION: CONDITIONALLY SAFE — BLOCKERS MUST BE RESOLVED**

Code audit of the **current** tablet flavor shows Android **will keep** the sandbox on a true upgrade (same id, same cert, higher versionCode), and the application **does not** recreate or clear the database on startup.

It is **not** confirmed safe to push an APK to the production data tablet yet because signing match is unproven, a full large-media backup cannot be verified with current ZIP code, and no physical in-place test has been run.

Do **not** claim 100% safety from source inspection. Physical upgrade test is mandatory.

---

## MANDATORY SAFETY MATRIX

| Data | Current Location | Survives In-Place APK Update? | Startup Risk | Future Phase Risk | Verification |
|------|------------------|-------------------------------|--------------|-------------------|--------------|
| `tablet_offline.db` | `getDatabasesPath()/tablet_offline.db` | **YES** if same applicationId+cert | Open v4 only | Keep version 4 | File exists; schema 4 |
| `cache` | SQLite table | YES | None | E writes status JSON | Row count + `locally_modified` keys |
| `pending_ops` | SQLite table | YES | None | B must not drop/incompatibly parse | Same IDs |
| `media_files` | SQLite table | YES | None | B keep `uploadOne` | Same IDs + paths |
| `local_users` | SQLite table | YES | `ensureDefaultAdmin` does not delete | B must not rotate salt | Same user_ids; offline login |
| `device_meta` | SQLite table | YES | Read `device_ready` | D reset only if user confirms | `device_ready` still `1` |
| SharedPreferences | app `shared_prefs` | YES | Salt created only if empty | Do not rename keys | `server_base_url`, `local_auth_salt_v2` present |
| Judge cookies | `app_flutter/.cookies_judge` | YES | Reopen jar | Logout/401 delete files only | Dir exists; expiry separate |
| Device cookies | `app_flutter/.cookies_device` | YES | Reopen jar | Device logout does not `deleteAll` device jar in hub logout (in-memory only) | Dir exists |
| Photos | `app_flutter/media/pending\|synced/images/` | YES | None | D synced-delete is explicit | Hash match |
| Videos | `…/videos/` | YES | None | B timeouts; do not delete | Hash match |
| Signatures | `app_flutter/judge_signatures/` + cache | YES | None | F UI only | File + sheet |
| PDF cache | `library_pdfs/`, `flow_day_pdfs/` | YES | None | Prefetch prune after online library fetch | Files open offline |
| Evaluation results | cache `saved_payload` / `saved_rows` | YES | Prefetch merges if local work | E status overlay | Open sheet |
| Notes | inside saved rows / polarity cache | YES | Same merge | E | Visual check |
| `locally_modified` | cache JSON | YES | Merge keeps it | E must keep | JSON flag |
| `locally_approved` | cache JSON | YES | Merge keeps unless server `reopened` | E / D reopen | JSON flag |

---

*End of Phase A.1. No implementation started. Do not start Phase B until user approval.*
