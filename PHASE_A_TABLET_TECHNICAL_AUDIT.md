# PHASE A — SMART ARBITRATION TABLET TECHNICAL AUDIT

**Status:** READ-ONLY ANALYSIS COMPLETE  
**Date:** 2026-10-16  
**App version inspected:** `flutter_app/pubspec.yaml` → `2.7.32+46`  
**Scope:** Flutter tablet app (`flutter_app/`) + tablet server API (`app/tablet_api.py` and related) as currently implemented.

---

## 0. PHASE A SAFETY VERIFICATION

| Check | Result |
|---|---|
| SOURCE FILES MODIFIED | **0** |
| DATABASE FILES MODIFIED | **0** |
| DATABASE SCHEMA MODIFIED | **NO** |
| MIGRATIONS CREATED | **0** |
| UI MODIFIED | **NO** |
| DEPENDENCIES CHANGED | **NO** |
| OPERATIONAL DATA MODIFIED | **NO** |
| LOCAL JUDGE DATA MODIFIED | **NO** |
| SYNC OPERATIONS EXECUTED AGAINST PRODUCTION | **NO** |

This document is analysis only. No implementation was started.

---

## 1. EXECUTIVE SUMMARY

The tablet is an offline-first Flutter application. Local durable state lives in SQLite `tablet_offline.db` (native) or IndexedDB (PWA). Judge work is queued as `pending_ops` with stable `client_op_id` values and uploaded by a single `SyncService`. Server downloads are merged with local unsynced sheets via `mergeServerCacheWithLocal` so locally modified records are not overwritten.

The 15 requested items are all implementable on the **current** architecture. **No database schema change is currently proven necessary.**

Highest-risk areas before any coding:

1. **Ethernet reconnect after offline login** — local session exists, Flask cookie session does not; auto-sync then 401s.
2. **Device Sync duration** — sequential per-judge, per-list, per-PDF HTTP with no parallelism and no incremental package.
3. **Save/Approve list status** — Save does not update list-aggregate status; Approve updates `status_label` but not `dispatch_label`.
4. **Large ZIP/media in RAM** — eval backup and local recovery encode complete archives in memory.
5. **Device reset** — existing control already calls `OfflineStore.clearAll()` (destructive). Future work must not use it as a repair tool.

---

## 2. CURRENT TABLET ARCHITECTURE

### A–X map (actual files)

| Item | File | Class | Function / method | Responsibility |
|---|---|---|---|---|
| A. Project root | `flutter_app/` | — | — | Flutter tablet/PWA app |
| B. Entry | `flutter_app/lib/main.dart` | — | `main()` | Init OfflineStore → ApiClient → Connectivity → SyncPreferences → DeviceAdmin → DevicePresence → Auth; start Health/Sync/Notifications/Presence; `runApp` |
| C. State | `flutter_app/lib/app.dart` | `LfTrainingEvaluationApp`, `_AuthRefresh` | Provider + `GoRouter.refreshListenable` | Auth/DeviceAdmin as `ChangeNotifier`; screens are StatefulWidgets; sync UI via `ValueNotifier`s |
| D. Local DB | `flutter_app/lib/services/offline_store.dart` | `OfflineStore` | `openDatabase` / PWA KV | Native: sqflite. Web: IndexedDB via `pwa_kv_store_web.dart` |
| E. DB location | `offline_store.dart` | `OfflineStore` | `_database` | `{getDatabasesPath()}/tablet_offline.db` schema v4 |
| F. Repository | `flutter_app/lib/services/tablet_repository.dart` | `TabletRepository` | `fetch*`, `save*`, `approve*`, `prefetchForOffline` | Screen data, cache keys, merge, pending enqueue |
| G. Auth | `flutter_app/lib/services/auth_service.dart` | `AuthService` | `login`, `_loginOffline`, `logout`, `refreshFromServer`, `prepareLocalAuth` | Online Flask login or local hash login; does **not** auto-restore session at boot |
| H. HTTP | `flutter_app/lib/services/api_client.dart` + `api_client_io.dart` | `ApiClient` | `_send`, `getBytes`, `uploadCriterionMedia`, `uploadMediaChunk`, `ping` | JSON + cookies; **new `HttpClient` per request** (`sendHttp`) |
| I. Server URL | `api_client.dart` | `ApiClient` | `init`, `setBaseUrl` | SharedPreferences `server_base_url`; default port 8005 |
| J. Sync | `flutter_app/lib/services/sync_service.dart` | `SyncService` | `start`, `enqueueLocalFirst`, `flush`, `runFullSync` | Pending queue + full sync (upload then download) |
| K. Upload | `sync_service.dart`, `media_upload_service.dart` | `SyncService`, `MediaUploadService` | `flush`, `_sendMedia`, `uploadOne` | Sequential pending ops; chunked media |
| L. Download | `package_sync_service.dart`, `tablet_repository.dart` | `PackageSyncService`, `TabletRepository` | `downloadAndStorePackage`, `updateMyData`, `prefetchForOffline` | Device package vs per-judge updates |
| M. Media | `media_upload_service.dart`, `tablet_repository.dart`, `app/tablet_media_resumable.py` | `MediaUploadService` | `queueCriterionMedia`, `uploadOne` | Local persist then chunked upload |
| N. Backup/restore | `eval_backup_service.dart`, `local_recovery_service.dart` | `EvalBackupService`, `LocalRecoveryService` | `createBackup`, `scan`, ZIP export | Two separate mechanisms (see §9) |
| O. Device Manager | `device_admin_service.dart`, `device_admin_hub_screen.dart`, `device_setup_screen.dart` | `DeviceAdminService`, `DeviceAdminHubScreen` | `login`, `downloadAndStorePackage`, `_resetDevice` | Local-only admin; **not** a judge |
| P. Judge Home | `home_screen.dart` | `HomeScreen` | `_load` → `fetchHome` | Menu + progress + incomplete table |
| Q. Evaluation lists | `evaluation_lists_screen.dart`, `eval_sheet_screen.dart` | `EvaluationListsScreen`, `EvalSheetScreen.evaluationList` | fetch/save/approve | قوائم تقييم الإجراءات |
| R. Dilemma / action eval | `action_eval_lists_screen.dart`, `eval_sheet_screen.dart` | `ActionEvalListsScreen`, `EvalSheetScreen.actionEval` | fetch/save/approve | قوائم تقييم المعاضل |
| S. Settings | `settings_screen.dart` | `SettingsScreen` | `_save`, `_test`, logout | Server URL, sync mode, signature, recovery, backup, logout |
| T. Exercise info | `exercise_details_screen.dart` | `ExerciseDetailsScreen` | tabs `info/general/specific/program/map` | Includes program image + map image |
| U. Map | `exercise_details_screen.dart` | `_WorkspaceImagePane` | tab `map` | Same payload as exercise details (`has_map`, image kind `map`) |
| V. Exercise program | `exercise_details_screen.dart` | `_WorkspaceImagePane` | tab `program` | Same payload (`has_program`, kind `program`) |
| W. Library | `library_screen.dart`, `library_pdf_cache.dart` | `LibraryScreen` | route `/library` | Also `/exercise-papers` with `exercisePapers: true` |
| X. Incomplete tasks | `incomplete_tasks_screen.dart` **and** `home_screen.dart` `_IncompleteTable` | `IncompleteTasksScreen` | `fetchIncomplete` | Dedicated route `/incomplete` already exists; Home also embeds the table |

Android native: `flutter_app/android/app/src/main/kotlin/ae/lf/training/lf_training_evaluation/MainActivity.kt` — MethodChannels `lf.training/storage` (free space) and `lf.training/recovery_export` (SAF ZIP save). No ConnectivityManager / NetworkCallback in Kotlin.

---

## 3. LOCAL DATA ARCHITECTURE

### Database: `tablet_offline.db` (schema version 4)

Tables (from `OfflineStore._createV2` / upgrades):

| Table | Role |
|---|---|
| `cache` | JSON payloads keyed by `cache_key` (+ `sync_status`) |
| `pending_ops` | Durable outbound queue (`id` = client_op_id) |
| `media_files` | Local photo/video records + sync status |
| `local_users` | Provisioned judges (username, password hash, session JSON) |
| `device_meta` | Device-admin package timestamps / ready flag |

User-scoped cache keys: `OfflineStore.userKey` → `u{userId}:{key}` examples:

- `u12:home`, `u12:evaluation_lists::`, `u12:action_eval_lists:`, `u12:evaluation_list_detail:{unit}:{id}`, `u12:action_eval_detail:{slot}`

### Names that DO exist (verified)

- `tablet_offline.db`
- `pending_ops`
- `client_op_id` (pending op `id` + request header `X-Client-Op-Id` / body field)
- `locally_modified`, `locally_approved` (inside cached sheet JSON)
- `media_files.local_path`

### Names that do NOT exist as tables

- No table literally named `locally_modified`
- No separate `pending_ops` server table (server uses `TabletClientOp`)

### How local unsynced data is protected from server downloads

**CONFIRMED** in `eval_cache_merge.dart` + `TabletRepository._downloadAndStore` / `provisionPutForUser`:

1. `cacheHasLocalJudgeWork` is true if cache `sync_status` is pending/failed/syncing **or** JSON `locally_modified` / `locally_approved`.
2. Then `mergeServerCacheWithLocal` copies server metadata but **keeps local** `saved_payload`, `saved_rows`, signature, `local_media`.
3. Exception: if server `workflow.reopened == true` and local is not `locally_modified`, local approval is cleared (chief-return path).

Pending ops are **not** deleted on download. They are removed only after a successful HTTP response in `SyncService.flush`.

`OfflineStore.clearAll()` **does** wipe cache + pending_ops + media_files + local_users. Used only by Device Manager reset. Must never be used as a repair.

---

## 4. CURRENT NETWORK ARCHITECTURE

```
ConnectivityService (connectivity_plus)
  hasNetwork / isLocalNetwork (wifi OR ethernet)
        ↓
HealthService.check() → ApiClient.ping()
  TCP Socket.connect(host, port) then GET /api/tablet/health
        ↓
ApiClient.online + HealthService.serverReachable
        ↓
SyncService._onConnectivityChanged / 20s timer
```

Facts:

- Ethernet **is** recognized: `ConnectivityResult.ethernet` (`connectivity_service.dart`).
- “Online” in the chip is **server reachable**, not merely a cable (`HealthService` comment + `probeServer`).
- Chip labels today: `Offline Mode` / `بانتظار المزامنة` / `جارٍ المزامنة` / `متصل بالسيرفر` / `فشل المزامنة`. There is **no** `جاري الاتصال بالسيرفر` state.
- HTTP: new `HttpClient` every call, `Connection: close`, cookies in `PersistCookieJar` under app documents `.cookies_judge` / `.cookies_device`.
- Two cookie jars: judge vs device (`ApiClient.withDeviceAuth`).
- Default sync mode is **manual** (`SyncPreferences` default `TabletSyncMode.manual`). Automatic upload/download only if the user selected automatic.
- Android manifest: `INTERNET`, `ACCESS_NETWORK_STATE`. No `CHANGE_NETWORK_STATE`. No native NetworkCallback.
- `ApiClient.uploadCriterionMedia` timeout **60 seconds** (legacy multipart). Chunked upload timeout **10 minutes** per chunk.

---

## 5. CURRENT SYNC FLOW

### CURRENT_SYNC_FLOW (actual names)

```
main()
  OfflineStore.init()
  ApiClient.init()
  ConnectivityService.init()
  AuthService.prepareLocalAuth()     // does NOT restore session
  HealthService.start()              // ping every 12s + on connectivity/resume
  SyncService.start()                // 20s timer; listeners on reachable/LAN

LOGIN (LoginScreen._submit → AuthService.login)
  ApiClient.ping(8s)
  if reachable → POST /api/tablet/auth/login  + persist cookies + local_users
  if not reachable AND local hash matches → AuthService._loginOffline
       (NO Flask cookies)
  if online login → TabletRepository.prefetchForOffline()
       (skipped when lastLoginWasOffline == true)

OFFLINE INIT (Device Manager only)
  PackageSyncService.setupLogin → POST /api/tablet/device/setup-login
  PackageSyncService.downloadAndStorePackage
       GET /api/tablet/device/manifest
       per judge: bootstrap, lists, details, flow, objectives, notes, incomplete
       PDFs sequentially
       DeviceAdminService.markDeviceReady()

LOCAL LOAD
  TabletRepository._cacheGetScoped / _readLocalFirst / fetchHome

CONNECTIVITY CHECK
  HealthService.check → ApiClient.ping → /api/tablet/health

DEVICE SYNC (admin)
  PackageSyncService.downloadAndStorePackage  (full package, all judges)

JUDGE FULL SYNC
  SyncService.runFullSync
    HealthService.ensureReachableForSync (0+2+3+5s)
    SyncService.flush                    // upload pending
    PackageSyncService.updateMyData      // GET /api/tablet/me/updates + prefetchForOffline

PENDING
  SyncService.enqueueLocalFirst → OfflineStore.enqueueOp (survives restart)

UPLOAD
  SyncService.flush  (single-flight via syncing ValueNotifier)
    sequential for each PendingOp
    media → MediaUploadService.uploadOne
    else ApiClient.post/put/delete with idempotencyKey = op.id

ACK
  HTTP 2xx → OfflineStore.removeOp
  approve → _markSheetSyncedAfterApprove

DOWNLOAD MERGE
  _downloadAndStore / provisionPutForUser → mergeServerCacheWithLocal
```

### Sync properties (verified)

| Question | Finding |
|---|---|
| Who can start sync? | Device Admin package download; judge `runFullSync` (settings/sync screen); automatic if `SyncPreferences.isAutomatic` |
| Automatic? | Only if mode == automatic **and** LAN + server reachable |
| Concurrent jobs? | `SyncService.syncing` and `_autoFullSyncRunning` gate full sync/flush. **Not a mutex across Device Sync + judge flush.** Device package download does not set `syncing`. |
| Retry | Flush: failed op `markOpFailed`; 20s timer retries flush if automatic. Media has pause/resume. |
| Timeouts | GET 45s default, POST 20s, package GET 90s, PDF 120s, ping 8s, media chunk 10 min, legacy multipart 60s |
| Pending survive restart | Yes — `pending_ops` SQLite |
| Duplicate upload | `client_op_id` + server `TabletClientOp` unique `(user_id, client_op_id)` |
| Scoped by user | `pendingOps(userId: currentUserId)`; cache keys `u{id}:` |
| Scoped by exercise | Pending ops store `exercise_id`; eval backup filters by session exercise. Device package is current server exercise |

---

## 6. DEVICE SYNC PERFORMANCE ANALYSIS

**Owner:** `PackageSyncService._downloadAndStorePackageImpl`  
**UI:** `DeviceSetupScreen`, hub button «تحديث حزمة التمرين (Device Sync)»

### What it downloads (order)

1. GET `/api/tablet/device/manifest` (judges + exercise)
2. Upsert each judge into `local_users` (sequential loop)
3. GET `/api/tablet/device/exercise-details` + images
4. **For each judge, sequential:**
   - GET `.../judge/{id}/bootstrap` (or extra `/home`)
   - GET evaluation-lists (default) + **each extra phase tab** + **each list detail**
   - GET action-eval + **each day tab** + **each list detail**
   - GET flow + **each day**
   - GET objectives, polarity-notes, incomplete
5. GET library + exercise-papers (shared), copy into each judge cache
6. GET each library PDF and each flow-day PDF **one after another** (`getBytes` 120s)
7. Verify required cache keys exist

### Bottlenecks

| # | Observation | Confidence |
|---|---|---|
| 1 | All judge/list/PDF HTTP is **sequential** (`for` loops, no `Future.wait`) | **CONFIRMED** |
| 2 | Each evaluation/action list fetches a **full sheet detail** during provision (`_provisionEvalDetails`, `_provisionActionDetails`) | **CONFIRMED** |
| 3 | Extra GET per phase tab and per flow/action day (duplicate list+detail traffic) | **CONFIRMED** |
| 4 | PDFs skip only if bytes already in `LibraryPdfCache` — no checksum/ETag/version from server | **CONFIRMED** |
| 5 | Large PDFs run **before** provision is marked ready; they block completion | **CONFIRMED** |
| 6 | Cache writes are per-key `cacheSet`, not a SQL transaction wrapping the judge | **CONFIRMED** |
| 7 | No pagination, no incremental manifest, no compression flag on these GETs | **CONFIRMED** |
| 8 | Default GET timeout 90s on provision; a single hung detail delays the whole judge | **CONFIRMED** |
| 9 | UI `setState` on every progress callback during hub re-download | **CONFIRMED** |
| 10 | JSON payload size “too large” | **NOT CONFIRMED** (not measured) |
| 11 | Same file downloaded twice across judges | **LIKELY** for per-judge details; shared library/PDF is once then copied |

**Root cause of slowness:** sequential chatty HTTP (judges × (phases + days + lists + PDFs)), not a second sync engine.

Do not optimize in Phase A.

---

## 7. DEVICE MANAGER PERMISSION ANALYSIS

Device Manager is **local**, not a `User` role in SQLite:

- Credentials: SharedPreferences `device_admin_username` / hash; default `manager` / `admin123`
- Router (`app.dart`): if `isLocalAdminSession`, **all judge routes redirect to `/device-admin`**
- Hub copy: «مدير الجهاز لا يستطيع فتح تقييمات المحكمين أو تعديلها.»

Judge evaluation data **already exists** on the tablet under `u{userId}:*` after Device Sync. Viewing all judges’ lists can be a **local cache UI** without schema change.

### Future actions vs current code

| Future action | Existing building block | Gap |
|---|---|---|
| A. View all judges’ lists | `OfflineStore.cacheGetForUser` + list screens | Router forbids Device Admin from judge routes; need a Device-Admin-only viewer |
| B. Return approved list like Chief Judge | Server: `apply_chief_reopen` in `app/evaluation_workflow.py` (web chief hub). Tablet sheet understands `workflow.reopened` | Device Admin has **no** Flask chief session. Need either a device-setup API to reopen or enqueue as the owning judge. **No new table required** — `reopened_for_judge` already exists |
| C. Photos/videos to Downloads | `media_files.local_path`; SAF channel only saves **one ZIP** (`saveZipCopy`) | No folder-tree Downloads writer yet |
| D. Excel to Downloads | `local_recovery_xlsx.dart`, `eval_backup_assembler.dart` already build xlsx from cache | Wire per-list export + SAF/share |
| E. Structured folders | Not implemented on tablet | Can do via SAF tree or MediaStore; Android 10+ has no `WRITE_EXTERNAL_STORAGE` in the manifest |

**Database schema change needed?** **NO** for view/export of local data. Return-to-judge **POSSIBLY** needs a new **API route** (not a new column) authenticated as device-setup.

---

## 8. DEVICE RESET CONTROL ANALYSIS

| | |
|---|---|
| Location | `device_admin_hub_screen.dart` |
| Widget | `TextButton` (not ElevatedButton), label **إعادة ضبط بيانات الجهاز** |
| Callback | `_resetDevice` |
| Confirm | `AlertDialog` — Cancel / «مسح الكل» |
| Function | `OfflineStore.clearAll()` then `DeviceAdminService.clearDeviceReady()` then `ensureDefaultAdmin()` |
| Deletes | cache, pending_ops, media_files, local_users, device_meta, library PDF cache |
| User/offline/media | **Yes — all local judge data and pending work** |
| Credentials | Device-admin defaults restored; judge offline hashes wiped; Flask cookies not explicitly cleared here |

Future: convert this **existing** control into a button. **Do not change behavior in Phase A.**  
Do **not** call `clearAll` as a fix for sync/status bugs.

---

## 9. BACKUP / RESTORE ANALYSIS

There are **two** current mechanisms:

### A. Local Recovery (Device Manager + Settings)

- UI: `/recovery` → `LocalRecoveryScreen`
- Service: `LocalRecoveryService` — **read-only scan**, then ZIP export
- Sources: **all** `pending_ops`, **all** cache rows, **all** media (not per-user unless filtered in UI)
- Format: ZIP (`archive` package), optional Excel inside
- Destination: app documents then SAF `ACTION_CREATE_DOCUMENT` (Downloads picker)
- Does **not** restore into `tablet_offline.db` from the tablet UI (comment: does not mutate source tables)
- Server-side restore code exists under `app/_local_bak_tablet_recovery_*` (backup folder naming) — treat as **not the live tablet path** unless separately confirmed wired

### B. Current-exercise eval backup (Settings, logged-in judge)

- UI: `/eval-backup` → `EvalBackupScreen`
- Service: `EvalBackupService.currentScope()` uses **current AuthService session** (one user, one exercise)
- Contents: per-list xlsx + local media + `manifest.json`
- Already **per logged-in user + current exercise**

### Large-file behavior (both ZIP paths)

| Behavior | Finding |
|---|---|
| Loads files into RAM | **CONFIRMED** — `readAsBytesSync`, `ZipEncoder().encode(archive)` full buffer |
| Streaming ZIP | **Not used** |
| Resume | **No** |
| App-level max size | **No** explicit cap |
| Storage check | Media upload checks free space; backup ZIP path does not fail-closed on low disk before encode |
| Integer limits | Dart `Uint8List` / ZIP in RAM will OOM on very large video sets — **LIKELY** field risk |

Future Device Manager “backup each user of current exercise separately” can reuse `EvalBackupService` / assembler with an explicit `userId` instead of `AuthService.session` — **no schema change**.

Judge self-backup of current exercise: **already exists** in Settings.

---

## 10. LARGE FILE / MEDIA TRANSFER ANALYSIS

### Client path (actual)

```
EvalSheetScreen pick photo/video
→ TabletRepository.queueCriterionMedia
   persistMediaFile (app docs)
   OfflineStore.upsertMedia
   enqueue PendingOp opType=media_upload
→ SyncService.flush → _sendMedia → MediaUploadService.uploadOne
   POST /api/tablet/media/upload/init
   POST /api/tablet/media/upload/chunk  (10 MB default, max 32 MB server)
   complete endpoint
```

Resumable chunked upload **does exist** (`app/tablet_media_resumable.py`, `kDefaultMediaChunkSize = 10MB`).

### Limits found

| Limit | Where | Value |
|---|---|---|
| Flask `MAX_CONTENT_LENGTH` | `app/__init__.py` | `None` (no Flask cap) |
| Chunk size | client + server | 10 MB default; server min 1 MB max 32 MB |
| Legacy multipart | `ApiClient.uploadCriterionMedia` | **60s timeout**; still in code |
| Chunk request | `uploadMediaChunk` | **10 minutes** |
| Reverse proxy | not in this repo | **NOT CONFIRMED** |
| Sequential flush | `SyncService.flush` | one op at a time; large video blocks later ops |
| Checksum | SHA-256 file + per-chunk | **CONFIRMED** |
| Duplicate | `client_uuid` / `client_op_id` on `EvaluationCriterionMedia` | **CONFIRMED** |

**Why large videos may still never finish — LIKELY, not fully proven in the field:**

1. Flush starts while `HealthService` flaps → `ApiOfflineException` breaks the loop, op stays pending.
2. Offline-login session has no cookies → 401 abort (`flush` breaks on 401/403).
3. Entire file still buffered per chunk in RAM (`chunkBytes` list).
4. If any remaining caller uses `uploadCriterionMedia` (60s), large files die. Primary queue path is chunked.

Do not remove limits in Phase A.

---

## 11. GENERAL PROGRESS COUNTER ANALYSIS

### HOME COUNTER SOURCE

- UI: `home_screen.dart` `_ProgressCard` → `StatsModel.completedCount` / `totalCount` / `completionPct`
- Data: `TabletRepository.fetchHome` → cache `home` or GET `/api/tablet/home`
- Server: `tablet_api._tablet_home_payload` → `_tablet_scoped_eval_status_rows` → `views._collect_all_eval_status_rows_flat`

`_collect_all_eval_status_rows_flat` concatenates:

1. All `EvaluationListPdfItem` for the exercise **filtered by assigned unit**, **not by phase**
2. All planner `ExercisePlannerFlowBundleActionEval` with `file_relpath` for that unit (all bundles/phases/days)

`status_done` = judge-approved (`eval_status_done`). Unentered lists still count in `total_count`.

### ACTION EVALUATION PAGE SOURCE

`TabletRepository.fetchActionEvalLists` / cache `action_eval_lists:{day}` — **current day tab**, published slots only.

### DILEMMA / PROCEDURE PAGE SOURCE

`fetchEvaluationLists` with **phase tab** (`preferFirstPhase` opens first phase only).

### Why the home number can look ~double

| Hypothesis | Confidence |
|---|---|
| Home totals **all phases**; evaluation page shows **one phase** | **LIKELY** (code has no phase filter on `_tablet_home_payload`) |
| Home = procedure lists **plus** action-eval lists; user compared to one page | **LIKELY** |
| Duplicate bundle slots counted twice in `_collect_all_eval_status_rows_flat` | **NOT YET CONFIRMED** (duplicate-empty purge exists elsewhere, not proven here) |
| `_overlayApprovedStatuses` matching `row['id']` across list types | **POSSIBLE** (slot/item/id overlap) — not proven to double `total_count` |

Safest future source of truth: **count the same lists the two pages show**, i.e. union of:

- evaluation-list rows the judge can open (unit + assigned phase(s))
- action-eval rows with files the judge can open (unit + days)

Recompute on tablet from those caches after local save/approve so home does not wait for `/api/tablet/home`.

Do not change calculations in Phase A.

---

## 12. HEADER ANALYSIS

Shared widget: `flutter_app/lib/widgets/app_header.dart` (`AppHeader`). Used by Home, Settings, lists, Device Admin, Incomplete, etc.

**Landscape (tablet) layout today:**

- **Right (visual RTL brand):** logo + «التحكيم الذكي» + «نظام إدارة التمارين» + exercise name (`brandLine3` / session exercise)
- **Center:** `pageTitle` + judge display name + unit (`pageSubtitle`)
- **Left (LTR action row):** optional خروج, Home, Back, Settings, Library, notifications, messages, pending-sync, online chip

Home currently passes `pageTitle: 'التمرين'` and `pageSubtitle: unitLabel`.

**Not duplicated as separate header implementations** — one shared widget. Phone compact header is a Column variant inside the same file.

Future requested layout (top-right system title, middle-right rank/name–unit, bottom-right exercise, center empty) is a **layout change inside `AppHeader` only**. Do not implement in Phase A.

---

## 13. INCOMPLETE TASKS ANALYSIS

| | |
|---|---|
| Embedded UI | Home `_IncompleteTable` under «المهام غير المكتملة» |
| Dedicated page | **Already exists:** route `/incomplete`, `IncompleteTasksScreen` |
| Home menu button | **Not present** in `_TABLET_MAIN_MENU` |
| Data | Same row family as home: server incomplete = `status_done == false` from `_collect_all_eval_status_rows_flat`; client extra-filters labels containing معتمد / منجز / ينجز |
| Navigation | Table rows open eval sheet; dedicated page uses `fetchIncomplete` |

Request 9: remove the **Home table/section**, not the feature.  
Request 10: add Home button routing to existing `/incomplete`.

---

## 14. HOME PAGE / NAVIGATION ANALYSIS

Server menu `_TABLET_MAIN_MENU` in `app/tablet_api.py` (current order):

1. مجرى الأحداث والمعاضل `/flow`
2. قوائم تقييم المعاضل `/action-eval`
3. قوائم تقييم الإجراءات `/evaluation-lists`
4. الإيجابيات والسلبيات `/positives-negatives`
5. أوراق التمرين `/exercise-papers`
6. الأهداف التدريبية `/objectives`

Home also hard-renames `evaluation_lists` title to «قوائم تقييم الإجراءات».

**Reuse, do not duplicate:**

| Future button | Existing route / widget |
|---|---|
| قوائم تقييم الإجراءات | `/evaluation-lists` |
| قوائم تقييم المعاضل | `/action-eval` |
| مجرى الأحداث والمعاضل | `/flow` |
| الإيجابيات والسلبيات | `/positives-negatives` |
| المهام غير المكتملة | `/incomplete` (exists, not in menu) |
| الأهداف التدريبية | `/objectives` |
| أوراق التمرين | `/exercise-papers` |
| برنامج التمرين | `ExerciseDetailsScreen` tab `program` — **same** `exercise_details` cache |
| الخريطة | `ExerciseDetailsScreen` tab `map` — **same** cache |
| المكتبة | `/library` (today also header `_SqIcon`) |

Settings: header `showSettings` → `/settings`. Future: Home bottom-right, ~2×, square.

---

## 15. SETTINGS ANALYSIS

### Settings button (Req 12)

- Widget: `AppHeader` `_SqIcon` (`Icons.settings_outlined`), 40×40 (34 compact)
- Route: `context.push('/settings')`

### «خروج» (Req 13)

**Two logout controls on Settings:**

1. **Header** (`AppHeader(showLogout: true)`): label **خروج** → `AuthService.logout()` (GoRouter then sends user to `/login`).
2. **Body** (`OutlinedButton`): label **تسجيل الخروج** → `AuthService.logout()` + `context.go('/login')`.

`AuthService.logout()` **is the legitimate auth logout**: best-effort POST `/api/tablet/auth/logout`, clear judge cookies, clear in-memory session, **does not** wipe `tablet_offline.db` or offline hashes.

If the future task is “remove THIS خروج button”, it is the **header `showLogout` on Settings**. Do **not** remove `AuthService.logout()` or the body «تسجيل الخروج» unless explicitly requested. Device Admin has a separate «تسجيل خروج مدير الجهاز».

---

## 16. EVALUATION STATUS WORKFLOW ANALYSIS

### Status vocabularies (they are not the same)

| Layer | Values |
|---|---|
| Server list `status_label` | `معتمد` / `لم ينجز` / `معاد للتقييم` (`eval_status_label_ar`) |
| Server `dispatch_label` | `لم يُرسل` / `بانتظار الإعتماد` / `مرسل` / `معاد للتعديل` (`eval_dispatch_status_ar`) |
| Requested future | SAVE → **بإنتظار الإعتماد**; APPROVE → **معتمد** |
| Local sheet JSON | `locally_modified`, `locally_approved`, `is_approved`, `can_edit`, `can_approve`, `workflow.label` |
| After local approve | `معتمد محلياً – بانتظار المزامنة` |
| After synced approve | `معتمد ومتزامن` |

### What Save actually does

`EvalSheetScreen._save` → `saveActionEvalResults` / `saveEvaluationListResults`:

- Writes sheet cache: `locally_modified=true`, `can_approve=true`
- Enqueues `PUT .../results` (`opType: save_results`)
- Returns immediately (`enqueueLocalFirst` → false)
- **Does not** call `_propagateListRowStatus`
- **Does not** set list `dispatch_label` / `row_tone: pending`

So Save is **A+C**: durable local save **and** queued submit, but the **list page status column does not change** until a later server download.

**CONFIRMED** mismatch vs requested SAVE = «بإنتظار الإعتماد».

### What Approve actually does

- Optionally saves first
- `_markLocallyApproved` + `_propagateListRowStatus(approved: true)` → sets `status_done`, `status_label=معتمد`, `row_tone=sent`
- **Does not set `dispatch_label`**
- List UI dispatch column uses `displayDispatch` (`dispatch_label` / `workflow_label`) → may still show «لم يُرسل» while the status pill shows «معتمد»

### Offline / sync / overwrite

- Pending save/approve survive restart
- Download merge keeps local payload if `locally_modified` / pending
- If `fetchHome` succeeds online, stats come from server then `_overlayApprovedStatuses` (approved sheets only — **not saved-but-unapproved**)

Race: user saves offline, home still shows old totals; if device is online, `fetchHome` server payload can ignore unsaved-unapproved local work for **counts** (overlay only strips/marks **approved** sheets).

Do not change status strings in Phase A.

---

## 17. ETHERNET AUTO-RECONNECT ROOT CAUSE ANALYSIS

### 15A — Startup / login / network

| # | Question | Answer |
|---|---|---|
| 1 | When is HTTP client created? | **Every request** (`sendHttp` new `HttpClient`, then `close(force: true)`) |
| 2 | When is network evaluated? | Boot ping; every 12s; connectivity_plus events; app resume; before sync |
| 3 | Permanently Offline-configured client? | **No** global client frozen offline. **Yes** for **session**: offline login never obtains cookies |
| 4 | DNS/socket cache | New client each time — **UNLIKELY** stale HttpClient. OS DNS still possible |
| 5 | HTTP client created offline stays invalid? | **Not** the HttpClient. **Session cookies** stay missing |
| 6 | Base URL change? | Only via Settings/`setBaseUrl` |
| 7 | Connectivity cached? | `ValueNotifier` last results; Health `_inFlight` single-flights pings |
| 8–10 | ConnectivityManager / NetworkCallback / connectivity_plus | Flutter `connectivity_plus` only; **no** Kotlin NetworkCallback |
| 11 | Ethernet recognized? | **Yes** (`ConnectivityResult.ethernet`) |
| 12 | Wi-Fi/mobile assumptions | LAN = wifi **or** ethernet; cellular is `hasNetwork` but **not** `isLocalNetwork` — auto full sync requires LAN |
| 13 | Connectivity vs reachability | Separated: interface vs `/api/tablet/health` |
| 14 | Login objects never recreated? | Cookie jar persists; offline login never fills it |
| 15 | Token refresh | Cookie session; `refreshFromServer` GET `/api/tablet/me`; on 401 **clears cookies**, keeps local session, **does not re-login** |
| 16–17 | Sync on network change | If **automatic** mode: flush pending + `_maybeAutoFullSync` (3 min cooldown) |
| 18 | Multiple sync jobs | Gated by `syncing` / `_autoFullSyncRunning`; Device Sync not in that gate |
| 19 | Manifest permissions | INTERNET + ACCESS_NETWORK_STATE present |
| 20 | Native Android network integration | Storage/SAF only |

### 15B — Effective state machine (actual `SyncUiState`)

```
offline  (serverReachable=false, pending=0)     → chip "Offline Mode"
pending  (offline or online with pending>0)
syncing
failed   (online, pending>0, lastError set)
synced   (online, pending=0, lastSuccessAt set) → "متصل بالسيرفر"
online   (online, pending=0, never synced)      → "متصل بالسيرفر"
```

Missing vs requested: **جاري الاتصال بالسيرفر**.  
«متصل بالسيرفر» today means health ping OK, **not** authenticated session OK.

### 15C — Session preservation

Offline login sets `_session` from `local_users.session_json` and **does not** call `/api/tablet/auth/login`.  
After Ethernet + health OK, `flush` / `updateMyData` use empty/expired judge cookies → **401** → flush abort → chip «فشل المزامنة».

User workaround (logout, recable, login) forces **online** `login()` which writes cookies.

**CONFIRMED** root cause: no silent re-authentication with stored credentials when the server becomes reachable, while keeping the same local session.

Minimum safe future change (not implementing now):

1. Detect `serverReachable` rising edge.
2. If local session exists and ping OK, `POST /api/tablet/auth/login` with stored username + **not** stored plaintext (password is hashed only). **OPEN QUESTION:** plaintext is not kept; online re-auth needs either a device-setup token, a refresh cookie, or a one-time stored secret. See §27.
3. Do not clear local session on 401.
4. Then `SyncService.flush` + `updateMyData` under existing single-flight.

### 15D — Auto sync safety (existing, reuse)

- `enqueueLocalFirst` + `client_op_id`
- `flush` skips if `syncing`
- merge keeps local work
- removeOp only after 2xx  
Reuse this engine. Do not add a second one.

Default sync mode is **manual** — even after reconnect, auto upload will **not** run unless the user enabled automatic. Reconnect UX must still allow manual «إدارة المزامنة» after silent re-auth.

---

## 18. CROSS-REQUIREMENT DEPENDENCIES

```
Req 15 (Ethernet / session cookies)
    ↓ unblocks
Req 6 (media upload) and Req 1 (Device Sync) and Req 14 (status after sync)
    ↓
Req 5 (large backup RAM) shares archive/media file IO with Req 6
Req 7 (progress) depends on same rows as Req 14 (status)
Req 2 (Device Manager lists) reads same cache as Req 4 (per-user backup)
Req 2 return-list uses same reopen flags as Req 14
Req 8–13 UI should wait until 7/14 sources of truth are decided
```

Shared objects: `ApiClient`, `HealthService`, `ConnectivityService`, `SyncService.syncing`, `OfflineStore`, `MediaUploadService`.

---

## 19. DATABASE IMPACT ASSESSMENT

| Requirement | DB schema change? | Reason | Alternative without schema change |
|---|---|---|---|
| 1 Device Sync speed | **NO** | Chatty HTTP / sequential IO | Parallelize + skip cached PDFs by size/hash in existing cache/files |
| 2 Device Manager lists | **NO** | Data already in `cache` / `media_files` | Admin UI over `cacheGetForUser`; optional new API for reopen |
| 3 Reset control | **NO** | Widget type only | Change `TextButton` → `ElevatedButton` |
| 4 Per-user backup | **NO** | `local_users` + scoped cache exist | Call assembler with explicit userId |
| 5 Large backup | **NO** | RAM ZIP algorithm | Stream Zip to file |
| 6 Large media | **NO** | Chunked protocol exists | Timeouts / session / sequential flush |
| 7 Progress count | **NO** | Counting logic | Filter/count existing list caches |
| 8 Header | **NO** | Layout | `AppHeader` |
| 9–11 Home nav | **NO** | Routes exist | Menu order + reuse screens |
| 12 Settings placement | **NO** | Layout | Home FAB/button |
| 13 Remove خروج | **NO** | `showLogout: false` | — |
| 14 Status workflow | **NO** | Fields exist | Propagate dispatch/status in cache JSON |
| 15 Ethernet | **NO** / **POSSIBLY** only if silent re-auth needs a stored refresh token | Cookies + local session exist | Re-login API or device-bound token **without** new eval tables |

**Default: NO MIGRATIONS.**

---

## 20. DATA SAFETY ASSESSMENT

Must preserve:

- `tablet_offline.db` (never delete as repair)
- `pending_ops` until server ACK
- `locally_modified` merge rule
- `local_users` hashes/sessions
- `media_files` paths
- Library PDF cache
- Judge `PersistCookieJar` (after online login)

Dangerous existing API: `OfflineStore.clearAll()` (Device reset).  
Device Sync `provisionPutForUser` already merges local work — keep that on any performance rewrite.

---

## 21. REGRESSION RISK ASSESSMENT

| Req | Risk | Why |
|---|---|---|
| 1 | **HIGH** | Wrong parallelism or skipping details can drop judge packages / mark device not ready |
| 2 | **HIGH** | Cross-judge visibility; reopen is a workflow/auth change |
| 3 | **MEDIUM** | Easy UI, but the control is already destructive |
| 4 | **HIGH** | Wrong user scope could export another judge’s results |
| 5 | **HIGH** | OOM / truncated ZIP / lost media |
| 6 | **CRITICAL** | Lost photos/videos; timeout changes can hide failed uploads |
| 7 | **MEDIUM** | Wrong counts vs list pages |
| 8 | **LOW** | Shared header — visual regressions on every page |
| 9–11 | **MEDIUM** | Navigation regressions; must not duplicate data stores |
| 12 | **LOW** | Layout |
| 13 | **MEDIUM** | Must not remove real logout elsewhere |
| 14 | **HIGH** | Incorrect معتمد / بانتظار can affect approval pipeline |
| 15 | **CRITICAL** | Session hijack if silent re-auth is sloppy; data stuck pending if 401 handling wipes queue |

---

## 22. CURRENT AUTOMATED TEST COVERAGE

### Flutter (`flutter_app/test/`)

| File | Covers |
|---|---|
| `eval_cache_merge_test.dart` | local vs server merge, `locally_modified` |
| `auth_offline_test.dart` | offline credential path |
| `eval_backup_assembler_test.dart` | backup package fields / client_op_id |
| `local_recovery_parser_test.dart` | recovery parse of pending_ops / cache |
| `eval_sheet_parse_test.dart` | sheet JSON, reopened/can_edit |
| `eval_sheet_scoring_test.dart` | scoring |
| `eval_sheet_screen_test.dart` | sheet widget (limited) |
| `signature_png_test.dart` | signature PNG |
| `widget_test.dart` | smoke |

**Missing (must exist before implementation):** connectivity reconnect, silent re-auth, `flush` 401 behavior, Device Sync request-count, progress counting vs list pages, save/approve list-status propagation, chunked upload retry, ZIP streaming.

### Python

No dedicated `tests/test_tablet*.py` in the live tree. Related: `tests/test_eval_header_narrative.py` (tablet omit keys), `tests/_local_bak_test_tablet_recovery_import.py` (backup folder). Server tablet API, health, idempotency, media chunk complete **lack live tests** in-tree.

---

## 23. REQUIRED FUTURE TESTS (DO NOT CREATE IN PHASE A)

1. Offline login → Ethernet up → health true → authenticated GET `/api/tablet/me` succeeds **without** logout (will fail today).
2. Disconnect/reconnect while staying logged in (online-origin session).
3. `flush` single-flight: two triggers → one in-flight.
4. Save then list page dispatch_label == بانتظار الإعتماد (after future fix).
5. Approve then status_label == معتمد and dispatch مرسل/معتمد as specified.
6. `mergeServerCacheWithLocal` still wins over `/me/updates`.
7. Home total equals procedure lists (scoped) + action-eval lists (scoped).
8. Device Sync skip PDF when local bytes present.
9. Backup ZIP per `userId` contains only that user’s lists.
10. Media chunk resume after process kill.
11. Device Admin cannot call `clearAll` from any new “repair” path.

Physical tablet tests: §26.

---

## 24. RECOMMENDED IMPLEMENTATION PHASES

Do **not** implement 1→15 in numeric order. Group by shared machinery.

### PHASE B — Network session + sync reliability  
**Reqs 15, 6, (partial 1)**  
Why first: Offline-login 401 makes media/sync/status look “broken” even if later code is correct. Reuse `SyncService`; add silent re-auth + «جاري الاتصال» state; then harden media timeouts on the **existing** chunked path.

### PHASE C — Backup / restore  
**Reqs 4, 5**  
Stream ZIP; Device Manager per-user current-exercise export; keep judge self-backup.

### PHASE D — Device Manager capabilities  
**Reqs 2, 3**  
Local list viewer for all `local_users`; Downloads via SAF; Excel from existing assemblers; reset control widget-only. Reopen-as-chief only after B (needs live server session).

### PHASE E — Evaluation truth  
**Reqs 14, 7**  
Propagate save/approve into list aggregates + home stats from the same two list sources.

### PHASE F — UI / navigation  
**Reqs 8–13, 10–11**  
Header layout, home button order, incomplete table removal, settings size/position, remove Settings header خروج, library from home.

**Why this order:** F without E still shows wrong counts; D reopen without B cannot sync; 1 full Device Sync rewrite is safer after HTTP/session is stable (finish remaining Req 1 parallelism at end of B or a B2).

---

## 25. EXACT FILES EXPECTED TO CHANGE IN EACH FUTURE PHASE

### Phase B
- `connectivity_service.dart`, `health_service.dart`, `auth_service.dart`, `api_client.dart`, `api_client_io.dart`
- `sync_service.dart`, `online_status_chip.dart`
- `media_upload_service.dart` (timeouts/retry only)
- Possibly `login_screen.dart` (no logout required)
- Server: `app/tablet_api.py` `/auth/login` + `/health` only if a device-bound re-auth endpoint is required  
**Not:** parallel new sync engine

### Phase C
- `eval_backup_service.dart`, `eval_backup_assembler.dart`, `eval_backup_screen.dart`
- `local_recovery_service.dart` (streaming only if still used)
- `MainActivity.kt` if folder destinations change

### Phase D
- `device_admin_hub_screen.dart`, `device_admin_service.dart`, `app.dart` (routes)
- New Device-Admin list viewer reusing list widgets (do not fork scoring)
- `app/tablet_api.py` only if chief-return must run as device-setup
- `_resetDevice` widget type in hub

### Phase E
- `tablet_repository.dart` (`_propagateListRowStatus`, save path, home overlay)
- `eval_sheet_screen.dart` (local status after save)
- `app/tablet_api.py` `_tablet_home_payload` / `_tablet_scoped_eval_status_rows` if server home remains the source

### Phase F
- `home_screen.dart`, `app_header.dart`, `settings_screen.dart`
- `app/tablet_api.py` `_TABLET_MAIN_MENU` order
- `exercise_details_screen.dart` only if program/map become standalone routes wrapping existing tabs

---

## 26. PHYSICAL TABLET TESTS REQUIRED

Mark **PHYSICAL ANDROID TABLET + Ethernet** (emulator/PWA cannot prove this).

### TEST 1 — Offline login then cable in

1. Start tablet **without** Ethernet.  
2. Login as provisioned judge (offline).  
3. Confirm chip Offline / not «متصل بالسيرفر».  
4. Enter evaluation data; Save locally; confirm pending_ops.  
5. Connect Ethernet **without logout**.  
6. Confirm automatic network detection (`connectivity_plus`).  
7. Confirm `/api/tablet/health` then **authenticated** API.  
8. Chip → «متصل بالسيرفر» only after reachability **and** usable session.  
9. Existing `SyncService.flush` uploads pending.  
10. `updateMyData` downloads.  
11. No duplicate lists; no lost scores/media.  

**Today this is expected to fail at step 7/9 without silent re-auth.**

### TEST 2 — Stay logged in, unplug/replug

1. Start from an **online-origin** session (cookies present).  
2. Disconnect Ethernet; continue offline; save.  
3. Reconnect; auto health; auto or manual sync; no logout; no app restart.

Also physical: Device Sync duration with real PDFs; large video chunk upload; backup ZIP of a user with videos.

---

## 27. OPEN QUESTIONS / UNCONFIRMED FINDINGS

1. **Silent re-auth secret:** password plaintext is not stored (SHA-256 + device salt only). Cannot replay `/api/tablet/auth/login` from hash. Options not decided: keep a device-scoped refresh token; use device-setup cookie to mint a judge cookie; or prompt PIN once. **NOT YET CONFIRMED** which the product will allow.
2. **Home count doubling** exact field evidence (two phases vs duplicate slots vs sum of two pages) needs a live exercise dump. **NOT YET CONFIRMED.**
3. **Reverse proxy / nginx body size** in deployment. **NOT YET CONFIRMED.**
4. Whether production Device Sync is always “all judges” on one tablet or a subset. Code always uses full `manifest.judges`.
5. Live wiring of `app/_local_bak_tablet_recovery_*` vs Flutter `LocalRecoveryService` only. Treat bak_* as **not** the tablet runtime until proven.
6. Default `SyncPreferences` is **manual** — even a perfect reconnect will not auto-upload unless the user enabled automatic. Product intent for Req 15 (“sync starts automatically”) may require changing that default — **product decision**, not proven from current default.

---

## TRACEABILITY MATRIX

| Req | Problem | Root Cause | Client Files | Server Files | DB Impact | Risk | Recommended Phase |
|-----|---------|------------|--------------|--------------|-----------|------|-------------------|
| 1 | Device Sync too slow | **CONFIRMED:** sequential per-judge/list/PDF HTTP; no incremental/ETag | `package_sync_service.dart`, `device_setup_screen.dart`, `device_admin_hub_screen.dart` | `app/tablet_api.py` `/device/*` | NO | HIGH | B (after session) / B2 |
| 2 | Device Manager cannot open all judges’ lists / return / download | **CONFIRMED:** router isolates admin; copy forbids judge screens. Reopen is web chief-only | `app.dart`, `device_admin_hub_screen.dart`, `offline_store.dart` | `evaluation_workflow.py` reopen; optional new tablet route | NO | HIGH | D |
| 3 | Reset control is a text link | **CONFIRMED:** `TextButton` `_resetDevice` → `clearAll` | `device_admin_hub_screen.dart` | — | NO | MEDIUM | D |
| 4 | Backup all users together vs per user | **CONFIRMED:** LocalRecovery scans all DB rows; EvalBackup is already current user+exercise | `local_recovery_service.dart`, `eval_backup_service.dart` | bak recovery (not live tablet) | NO | HIGH | C |
| 5 | Large backup | **CONFIRMED:** full ZIP in RAM (`ZipEncoder.encode`) | `eval_backup_service.dart`, `local_recovery_service.dart`, `MainActivity.kt` | — | NO | HIGH | C |
| 6 | Large photo/video sync fails | **CONFIRMED limits:** 60s legacy multipart; sequential flush. **LIKELY** 401 after offline login / health flap. Chunked path exists | `media_upload_service.dart`, `api_client.dart`, `sync_service.dart` | `tablet_media_resumable.py`, `tablet_api.py` media | NO | CRITICAL | B |
| 7 | Home progress ~double | **LIKELY:** home counts all phases × both list types; pages show one phase/day. **NOT YET CONFIRMED** duplicate rows | `home_screen.dart`, `tablet_repository.dart` overlay | `tablet_api.py` `_tablet_home_payload`, `views._collect_all_eval_status_rows_flat` | NO | MEDIUM | E |
| 8 | Header layout | Current shared `AppHeader` layout ≠ requested | `app_header.dart` | — | NO | LOW | F |
| 9 | Incomplete list on Home | **CONFIRMED:** `_IncompleteTable` on Home | `home_screen.dart` | — | NO | LOW | F |
| 10 | Dedicated incomplete + home button | Page `/incomplete` exists; not in menu | `incomplete_tasks_screen.dart`, `home_screen.dart`, `app.dart` | `_TABLET_MAIN_MENU` | NO | LOW | F |
| 11 | Home button order + program/map/library | Menu order in API; program/map are exercise-details tabs; library is header | `home_screen.dart`, `exercise_details_screen.dart`, `library_screen.dart` | `tablet_api.py` `_TABLET_MAIN_MENU` | NO | MEDIUM | F |
| 12 | Settings to Home bottom-right 2× square | Header `_SqIcon` 40px | `app_header.dart`, `home_screen.dart` | — | NO | LOW | F |
| 13 | Remove Settings خروج | **CONFIRMED:** header `showLogout: true` is full `AuthService.logout` | `settings_screen.dart`, `app_header.dart` | `/api/tablet/auth/logout` | NO | MEDIUM | F |
| 14 | Save/Approve status not updating | **CONFIRMED:** Save does not propagate list rows; Approve sets `status_label` not `dispatch_label`. Requested labels differ from server dispatch vocabulary | `eval_sheet_screen.dart`, `tablet_repository.dart` | `evaluation_workflow.py`, `tablet_api.py` save/approve | NO | HIGH | E |
| 15 | Ethernet after offline login fails until logout | **CONFIRMED:** `_loginOffline` has no Flask cookies; no silent re-auth; flush aborts on 401. Cable cycle **LIKELY** extra OS event, not proven as the only cause | `auth_service.dart`, `health_service.dart`, `sync_service.dart`, `api_client_io.dart`, `login_screen.dart` | `tablet_api.py` `/health`, `/auth/login` | NO (token design TBD) | CRITICAL | B |

---

*End of Phase A report. No implementation started.*
