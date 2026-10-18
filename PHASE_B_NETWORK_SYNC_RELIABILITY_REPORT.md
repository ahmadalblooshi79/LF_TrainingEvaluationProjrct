# PHASE B — NETWORK SESSION & SYNC RELIABILITY REPORT

**Version:** 2.7.33+47  
**Flavor:** tablet  
**applicationId:** `ae.lf.training.lf_training_evaluation`  
**SQLite schema:** 4 (unchanged)

---

## 1. Executive Summary

Phase B restores a **legitimate Flask judge session** after offline login when Ethernet/server become available, then runs the **existing** `SyncService.runFullSync` once (even if global sync mode is manual). Local data, pending ops, media, and users are not deleted on 401 or reconnect failure.

Device Sync list-detail and PDF downloads now use **bounded concurrency (4)** and PDF files are streamed to disk via a `.part` then rename.

## 2. Confirmed Original Root Cause

Offline login creates a local `AuthService` session but **no Flask cookie**. Later `HealthService.ping` succeeds unauthenticated. Authenticated APIs return **401**. `refreshFromServer` cleared cookies and kept the local session but never re-authenticated. Default sync mode is manual.

## 3. Authentication Recovery Design

See `PHASE_B_AUTH_SECURITY_DECISION.md`.

Order:

1. `GET /api/tablet/me` if cookies already valid for the same user  
2. `POST /api/tablet/auth/reconnect` with HMAC ticket  
3. Existing `POST /api/tablet/auth/login` using Device-Sync seed **only if** `credentialDigest` matches stored `local_users.password_hash` (military number or username)  
4. Fail closed: stay local, show disconnected, keep data

## 4. Security Decision

| Gate | Value |
|---|---|
| DB schema change | **NO** |
| New Flutter/Python auth dependency | **NO** |
| Plaintext password stored | **NO** |
| Device Manager impersonation | **NO** |
| Local hash as bearer | **NO** |

## 5. Network State Machine

```
غير متصل بالسيرفر   health=false OR (health && !authenticated && !connecting)
جاري الاتصال بالسيرفر  health check in flight OR session recovery in flight
متصل بالسيرفر       health=true AND authenticated judge session usable
```

Plus existing overlays: جارٍ المزامنة / بانتظار المزامنة / فشل المزامنة.

Ethernet up ≠ متصل بالسيرفر.

Implemented in `resolveSyncUiState` + `OnlineStatusChip`.

## 6. Ethernet Detection

Unchanged: `connectivity_plus` wifi **or** ethernet → `isLocalNetwork`. No native NetworkCallback added.

## 7. Server Reachability

Unchanged `HealthService` ping of `/api/tablet/health` (plus TCP). Added `connecting` notifier during the ping.

Flask `PERMANENT_SESSION_LIFETIME` = 180 days.

## 8. Authenticated Session Verification

`AuthService.serverSessionUsable` is true only after `/me`, reconnect, or online login succeeds for the **same** `user_id`.

## 9. Reconnect-Specific Auto Sync

`SyncService._onServerBecameReachable`:

- Rising edge of `serverReachable` while a judge is logged in locally  
- Recover session  
- `runFullSync` **once** even if `tablet_sync_mode` is **manual**  
- Debounce 4s; skipped if a sync is already running  
- Does **not** change the stored global preference

App resume: if health OK, logged in, and session not usable → same path.

## 10. Single-Flight Protection

Existing `syncing` + `_autoFullSyncRunning` + new `_reconnectSyncInFlight`. Duplicate connectivity events collapse.

## 11. 401 Handling

- Local session kept  
- Cookies may be cleared  
- No `clearAll`, no `removeOp`, no media/user deletion  
- `flush` restores op to `pending`, attempts recovery once, retries that op once, otherwise **keeps** the op  
- Bounded backoff on failed recovery (2s / 8s / 30s)

## 12. Local Data Protection

`mergeServerCacheWithLocal` unchanged. Downloads still merge when `locally_modified` / `locally_approved` / pending cache status.

## 13. pending_ops Backward Compatibility

`PendingOp.fromRow` still reads 2.7.31/2.7.32 columns. Unknown `op_type` → `unknown` (still uploaded via method/path). Endpoints for save/approve/media/polarity/signature **unchanged**.

## 14. Media Queue Backward Compatibility

`LocalMediaRecord.fromRow` still reads old rows (`local_path`, optional `upload_session_id`). Chunked `uploadOne` unchanged protocol. Judge does not re-pick files.

## 15. Large Media Improvements

- Primary path remains chunked 10 MB (`MediaUploadService.uploadOne`)  
- Legacy `uploadCriterionMedia` has **no callers**; left in place  
- Chunk failures: keep file + record + `upload_session_id`; retry up to 3 with backoff  
- 401 on chunk: keep everything, pause status, recovery via flush  
- `markMediaSynced` still only after complete ACK  
- No new total file-size cap

## 16. Device Sync Performance Before/After

| | Before (2.7.32) | After (2.7.33) |
|---|---|---|
| List details | Sequential GET per list | Bounded **4** concurrent GETs |
| PDFs | Sequential `getBytes` (full RAM) | Skip if cached; else stream to `.part` then rename; concurrency **4** |
| Judges | Sequential | Sequential (dependent progress/readiness) |
| Local unsynced | `provisionPutForUser` merge | Unchanged |
| Failure | `clearDeviceReady` only; cache kept | Unchanged (no cache wipe) |

No physical wall-clock measurement in this session.

Concurrency limit **4** matches `HttpClient.maxConnectionsPerHost` and avoids unbounded `Future.wait`.

## 17. Files Modified

**Server:** `app/tablet_reconnect.py` (new), `app/tablet_api.py`, `app/__init__.py`  
**Flutter:** `auth_service.dart`, `sync_service.dart`, `health_service.dart`, `online_status_chip.dart`, `api_client.dart`, `api_client_io.dart`, `api_client_web.dart`, `media_upload_service.dart`, `package_sync_service.dart`, `library_pdf_cache*.dart`, `pubspec.yaml`, `BUILD_TABLET.bat`  
**Tests:** `flutter_app/test/phase_b_network_sync_test.dart`, `tests/test_tablet_reconnect.py`  
**Docs:** `PHASE_B_AUTH_SECURITY_DECISION.md`, this report

## 18. Functions Modified / Added

- `AuthService.recoverServerSession`, `matchingProvisionPassword`, `persistReconnectTicket`  
- `SyncService._onServerBecameReachable`, `resolveSyncUiState`  
- `HealthService.connecting`  
- `PackageSyncService.runBounded`, streamed PDF download  
- `issue_reconnect_ticket` / `verify_reconnect_ticket` / `tablet_auth_reconnect`

## 19. Server Endpoints Added/Modified

| Endpoint | Change |
|---|---|
| `POST /api/tablet/auth/reconnect` | **New** |
| `POST /api/tablet/auth/login` | Adds `reconnect_ticket` |
| `GET /api/tablet/device/manifest` | Session includes ticket |
| `GET /api/tablet/health` | Unchanged |

## 20. Database Impact

**NO** schema change. **NO** migrations. `openDatabase(version: 4)` unchanged.

## 21. Dependencies Impact

**NO** new pubspec/pip authentication dependencies. Signing config unchanged (debug release key, as before).

## 22. Automated Tests

| Suite | Result |
|---|---|
| `tests/test_tablet_reconnect.py` | **PASS** (6) |
| `flutter_app/test/phase_b_network_sync_test.dart` | **PASS** |
| `eval_cache_merge_test`, `auth_offline_test`, eval sheet/backup tests | **PASS** |
| `widget_test.dart` LoginScreen | **FAIL** (pre-existing overflow / two “تسجيل الدخول” widgets on a tiny viewport; login_screen not modified in Phase B) |

## 23. Regression Tests

Covered by existing Flutter tests for merge, offline hash, scoring, parse, backup. Manual/physical still required for Ethernet.

## 24. Physical Tablet Tests Required

TEST 1–4 from the Phase B spec on a **non-production** tablet:

1. Offline login → save → Ethernet in → connecting → connected → one sync  
2. Unplug / replug while logged in  
3. Ethernet up, Flask down → not “متصل بالسيرفر”  
4. Expired cookie → recover without local logout  

Then in-place upgrade `2.7.32+46 → 2.7.33+47` (`adb install -r` only).

## 25. APK Upgrade Safety

| Item | Value |
|---|---|
| APPLICATION ID | `ae.lf.training.lf_training_evaluation` |
| TABLET FLAVOR | tablet |
| VERSION NAME | 2.7.33 |
| VERSION CODE | 47 |
| SQLITE SCHEMA | 4 |
| DATABASE MIGRATION | NO |
| OfflineStore.clearAll on startup | NO |
| Existing pending_ops deleted | NO |
| Existing media_files deleted | NO |
| Existing local_users deleted | NO |
| local_auth_salt_v2 changed | NO |
| applicationId changed | NO |
| signing configuration changed | NO |
| uninstall required | NO |

## 26. Known Limitations

- Judges who offline-logged with a **custom** password that is neither military number nor username, and who have **no** ticket yet, cannot silent-reconnect until they complete one online login or Device Sync (ticket issued). Roster Device-Sync judges (password = military number) **can**.  
- Stolen tablet with a valid ticket can reconnect as that judge (same class of risk as stolen cookies / military-number password).  
- Device Sync wall-clock not measured here.  
- `widget_test` login overflow is pre-existing and out of Phase B scope.

## 27. Final Verdict

Phase B implementation is complete for in-place test APK 2.7.33+47. **Physical Ethernet tests are mandatory** before the production data tablet.

DO NOT START PHASE C until the user reviews physical results.
