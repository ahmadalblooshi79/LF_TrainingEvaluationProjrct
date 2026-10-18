# PHASE B — AUTHENTICATION RECOVERY SECURITY DECISION

**Status:** APPROVED TO IMPLEMENT (no schema change, no plaintext password store, no new dependency)  
**Date:** 2026-10-16

---

## 1. Current offline authentication model

- Device Sync provisions `local_users` with `username`, `military_number`, `password_hash`, `session_json`.
- Offline hash is `SHA-256("lf.v2|{local_auth_salt_v2}|{username}|{seed}")`.
- Device Sync seed is `local_password_seed` = military number (else username). The seed is hashed immediately; plaintext seed is **not** stored as a password field.
- `military_number` is already stored as identity metadata.
- `AuthService._loginOffline` restores an in-memory `SessionBundle` from `session_json`. It does **not** call Flask and does **not** write judge cookies.
- Plaintext judge password is **not** stored.

## 2. Current online authentication model

- `POST /api/tablet/auth/login` with username + password.
- Server `verify_password` against `User.password_hash`.
- Flask `session["user_id"]`; `session.permanent = True`.
- Roster-created judges use **username = military number** and **password = military number** (`app/views.py`).
- Device setup is a **separate** cookie jar (`device_setup=True`) and must not impersonate a judge session.

## 3. Exact reason reconnect fails

1. Offline login never obtains a Flask session cookie.
2. Later Ethernet + `HealthService.ping` (`GET /api/tablet/health`) succeeds **without** authentication.
3. `SyncService.flush` / `updateMyData` then hit `_require_judge_json` → **401**.
4. `refreshFromServer` on 401 clears cookies but **keeps** the local session; it does **not** re-login.
5. Default Flask permanent cookie lifetime is **31 days**; leftover cookies from an old online login may already be expired.
6. Global sync preference defaults to **manual**, so even health-up does not upload unless the user taps sync — Requirement 15 still needs a **reconnect-specific** one-shot.

## 4. Candidate approaches

| Approach | Schema? | Plaintext password? | New dep? | Verdict |
|---|---|---|---|---|
| Store plaintext password | No | **YES — FORBIDDEN** | No | STOP |
| Send `password_hash` as bearer | No | No, but **bypasses** Flask verify | No | STOP |
| Device Manager local `manager/admin123` impersonates judges | No | No | No | STOP |
| Device-setup cookie mints arbitrary judge session | No | No | No | Rejected (impersonation) |
| New refresh-token table | **YES** | No | No | STOP per Phase B gate |
| HMAC reconnect ticket in existing `session_json` / prefs + existing `/auth/login` for provisioned seed | **NO** | **NO** | **NO** | **SELECTED** |

## 5. Selected approach

**A. Server-issued HMAC reconnect ticket (primary)**

- Issued only after a **legitimate** Flask authentication (`/auth/login`) or during **device-setup** provision (already authorized to deliver that judge’s offline seed).
- Token = HMAC-SHA256(`SECRET_KEY`, payload) with `user_id`, optional `device_id`, expiry (~180 days).
- Stored on tablet in SharedPreferences `reconnect_ticket_u{userId}` and copied into existing `session_json` JSON (no new column).
- `POST /api/tablet/auth/reconnect` verifies HMAC, `User.is_active`, `can_access_judge_hub`, user_id match, optional device bind, then `session["user_id"] = judge` — same as login.

**B. Provision-seed replay via existing `/auth/login` (compatibility for 2.7.31/2.7.32 tablets with no ticket yet)**

- Reconstruct candidate password **in memory only** if and only if `credentialDigest(username, candidate)` matches stored `local_users.password_hash`.
- Candidates: existing `military_number`, then `username` (the same seeds Device Sync already used).
- Call **existing** `POST /api/tablet/auth/login` (real `verify_password`).
- Do not persist the reconstructed secret.
- If hash does not match those seeds (custom password, no ticket): remain local, show disconnected, **do not logout**, **do not delete data**.

**C. Cookie reuse**

- If `GET /api/tablet/me` already succeeds for the same user_id, skip recovery.

## 6. Why this does not bypass authentication

- Ticket is created only with `SECRET_KEY` after login or device-setup provision.
- Replay path uses Flask `verify_password`, not the local hash as a bearer.
- Recovered session user_id **must equal** the currently logged-in local judge.
- Inactive users / non-judge roles are rejected.
- Device Manager local password cannot call reconnect.

## 7. Credential storage

| Item | Storage |
|---|---|
| HMAC ticket | SharedPreferences + optional `session_json` field |
| Judge password | **not stored** |
| Local hash / salt | unchanged (`local_users.password_hash`, `local_auth_salt_v2`) |

## 8. Credential scope

- One ticket → one `user_id`.
- Optional bind to `X-LF-Device-Id`.
- Cannot switch judge identity.

## 9. Expiration

- Ticket `exp` ≈ 180 days.
- Flask `permanent_session_lifetime` set to 180 days so cookies last across long exercises.
- Expired ticket → try seed login if hash matches; else stay local.

## 10. Revocation

- `User.is_active == False` or lost judge-hub permission → reconnect 403.
- Rotating `SECRET_KEY` invalidates tickets (ops event).
- No server token table; no per-ticket revoke list (accepted limitation).

## 11. Server changes

- `app/tablet_reconnect.py` (HMAC helpers)
- `POST /api/tablet/auth/reconnect`
- Issue ticket on `/auth/login` and device manifest/session
- `PERMANENT_SESSION_LIFETIME` 180 days

## 12. Flutter changes

- `AuthService.recoverServerSession`
- Reconnect one-shot in `SyncService` (even if global mode is manual)
- Connection chip states
- 401: recover, do not delete pending/media/users, do not local-logout

## 13. Gates

| Gate | Value |
|---|---|
| DATABASE SCHEMA CHANGE REQUIRED | **NO** |
| NEW DEPENDENCY REQUIRED | **NO** |
| PLAINTEXT PASSWORD STORAGE REQUIRED | **NO** |

## 14. Security risks (accepted)

- Stolen tablet containing a valid ticket can reconnect as that judge (same as stolen device with cookies / military-number password).
- Seed replay sends military number over HTTP if the deployment uses cleartext LAN (`usesCleartextTraffic`) — identical to today’s online login.
- No server-side ticket revoke list.

## 15. Existing pending data protection

- Recovery never calls `clearAll`, never `removeOp` on 401, never deletes `media_files` / `local_users`.
- `mergeServerCacheWithLocal` unchanged.
- `client_op_id` / paths unchanged so 2.7.31/2.7.32 pending ops remain uploadable after in-place APK update.
