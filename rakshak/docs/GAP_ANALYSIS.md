# RAKSHAK — Gap Analysis (Step 1 — Phase 0 Audit, rebuilt)

REBUILT 2026-09-22 from a fresh line-by-line re-read of the code on disk. The
previous version of this document cited an "AGENT BUILD & VERIFICATION SPEC v1
§3" that **is not in the repository** (see limitation `HANDOFF`/`AGENT_BUILD_SPEC`
missing), so every one of its file rows is dropped. The only authoritative spec
is `docs/PROJECT_INFO.md` (READ FIRST, DO NOT EDIT). Every verdict below was
re-verified against the actual source this step.

> **PHASE 1 DELTA (2026-09-22):** rows marked 🔧 below were fixed during Phase 1
> (Step 2) and re-verified: `auth.py`, `deps.py`, `sightings.py`, the sighting
> schema, and the tests that now pass against them. Unit verdict is now
> **131 passed / 0 failed**. `scheduler.py` (§10 retention) remains the only
> HIGH-gap row pending Phase 5.
>
> **PHASE 2 DELTA (2026-09-22):** `InvalidStateTransition` is now raised where the
> spec requires a typed exception — `services/verification.py` (Step 3) and
> `api/hotlist.py` `_apply_status_update` — so the 409 handler in `main.py` is
> live. Unit verdict is now **132 passed / 0 failed**.
>
> **PHASE 3 DELTA (2026-09-22):** Step 4 was a verification pass over the already
> implemented device-registration/encrypted-sync stack. Added the two missing
> exit-criteria tests: AES-GCM tamper detection on **both** ciphertext and IV
> bit-flips (test_crypto.py), and proof that the raw device token/key is stored
> bcrypt-hashed and returned exactly once (test_device_sync.py). Verdict is now
> **136 passed / 0 failed**.
>
> **PHASE 4 DELTA (2026-09-22):** Step 5 privacy sweep found one real
> adversarial defect: an empty `plate` string passed schema validation and made
> `normalise_plate` raise `ValueError` → the whole batch 500'd. `api/sightings.py`
> now catches it and drops as `plate_not_hotlisted` (200). Added 2 malicious-
> client tests (empty plate 200-drop; mixed hotlisted/non-hotlisted batch
> isolation). Verdict is now **138 passed / 0 failed**.
>
> **PHASE 5 DELTA (2026-09-22):** Step 6 closed the last HIGH gap —
> `services/scheduler.py` now implements the full §10 policy: sightings > 90d
> purge **with their photos** (best-effort blob delete after row removal) and
> 1-year audit-log purge, in addition to the existing 30d rejected-complaint and
> 180d-after-cooldown hotlist purges. `purge_old_data` accepts injected
> `db`/`storage` for unit testing. New `tests/test_retention.py` (4 tests).
> Verdict is now **142 passed / 0 failed** — 0 NO rows remain.
>
> **PHASE 6 DELTA (2026-09-22):** Step 7 re-verified Phase 6 (analytics + admin)
> against §6 and §14A1. All 6 analytics endpoints, all 3 admin endpoints, and
> every audit-write path already match the spec. Added 2 tests closing real
> coverage gaps: `recovery-metrics` weekly series (recovered/expired counts +
> `recovery_rate`) and the `from`/`to` window aliases (old sighting excluded at
> default 30d, reappears with a 60d bound). Verdict is now **144 passed /
> 0 failed**.
>
> **PHASE 7 DELTA (2026-09-22):** Step 8 (dashboard hardening) — first phase
> where the frontend toolchain became runnable: `npm install` succeeded (registry
> reachable), `tsc --noEmit` and `npm run build` both pass. Hardening changes:
> (1) `api/hotlist.py` detail sightings now expose `photo_url` and the vehicle
> detail page renders a lazy-loaded thumbnail column (closes the
> stored-but-never-rendered photo gap, #28); (2) `AdminPanel.tsx` gained prev/next
> pagination on both the users and audit tables (was hardcoded to page 1, #24),
> with the role filter resetting to page 1. Backend verdict **145 passed /
> 0 failed**; dashboard `tsc` clean.
>
> **PHASE 8 DELTA (2026-09-22):** Step 9 (mobile on-device pipeline) — mobile
> toolchain became runnable (`npm install`, `tsc --noEmit` clean, Jest). Found and
> fixed a **real Phase-1 contract drift defect**: `services/queue.ts` typed the
> ingest `reasons` as `string[]` and checked `.includes("throttled")`, but the
> backend (since Phase 1) returns `reasons: [{index, reason}]` dicts — throttled
> hits were misclassified as ``rejected``. Extracted a pure exported
> `classifyDelivery(accepted, reasons)` and added a 4-test suite locking the
> classification. Jest is now **26/26** (22 match + 4 queue), including a
> "never misclassifies throttled as rejected" guard.
>
> **PHASE 9 DELTA (2026-09-22):** Step 10 (simulator + demo data) — installed
> the minimal simulator runtime (`numpy`, `opencv-python-headless`, `requests`;
> PyPI reachable) so the host-side Flow C pipeline is importable for the first
> time (`python scripts/device_simulator.py --help` no longer dies on
> `ModuleNotFoundError: cv2`). Added `backend/tests/test_device_simulator.py`
> (**15 tests**) covering §8 plate normalisation parity, Flow C quality gating
> (blur/dark rejection), 3-of-5 temporal voting, JPEG encoding, and the SQLite
> offline-queue flush roundtrip (accepted→deleted, 5xx→kept, empty→no-op).
> `data/samples/` remains unreachable (github blocked — limitation #56) and the
> full compose demo still needs a Docker-capable host. Verdict now
> **160 passed / 0 failed**; audit **0 violations (68 files)**.
>
> **PHASE 10 DELTA (2026-09-22):** Step 11 final docs pass — corrected
> `API.md` (ingest `reasons` is `[{index, reason}]` objects, not bare strings;
> login returns top-level tokens + `user`, not the register envelope) and
> `ARCHITECTURE.md` (§10 nightly job now lists audit-log 1y retention and
> photo-blob deletion). Two stale KNOWN_LIMITATIONS entries resolved:
> **#41** (spec never required `{"error"}` and handlers exist since Phase 1)
> and **#44** (`AuditLog.actor_id` is already `nullable=True`). Credential
> cross-check: `seed_db.py` ↔ `RUNBOOK` ↔ `DEMO_SCRIPT` ↔ `start_demo.sh` ↔
> `README` all agree on the volunteer account. Final sweep: pytest
> **160/0**, audit **0 violations (68 files)**, dashboard `tsc`+build PASS,
> mobile `tsc`+jest **26/26**. §8 composed acceptance remains **BLOCKED**
> (`docker` not installed; `wsl -l -v` → no distribution).

Interface truth for the audit:

- **Error shape:** PROJECT_INFO does not require `{"error": {...}}`; every
  consumer (all 14 test files, dashboard `lib/api.ts`, mobile `services/api.ts`)
  expects FastAPI's default `{"detail": "<string>"}`. Fixed in Phase 1 —
  `require_role` and every `main.py` handler now return a string detail.
- **Auth contract:** tests + dashboard + mobile agree —
  register → `{user, tokens:{access_token, refresh_token, token_type}}`;
  login → top-level `{access_token, refresh_token, token_type}`;
  refresh → accepts `{refresh_token}` in the body, returns
  `{access_token, refresh_token}`. Matched by `api/auth.py` since Phase 1.
- **Baseline pytest:** 115 passed / 13 failed (auth 6, privacy 4, sightings 3)
  — the Phase 0 starting point; current verdict is in the baseline table below.

## File-by-file audit table

| File | Exists? | Matches contract? | Gap description | Priority |
|---|---|---|---|---|
| **backend/app/main.py** | YES | PARTIAL | Exception handlers (AppError, InvalidStateTransition, catch-all INTERNAL_ERROR), CORS from `settings.CORS_ORIGIN`, static photo mount, ws+detect routers included. `/healthz` AND `/api/v1/healthz` both served (deliberate hedge — limitation #49). Detect endpoint included (prototype fallback). | MED |
| **backend/app/config.py** | YES | YES | All 16 fields declared; `_validate_master_key` rejects empty/non-base64/non-32-byte; zero undeclared `settings.*` references. | DONE |
| **backend/app/db.py** | YES | YES | PG engine + `SessionLocal` + `get_db`; conftest overrides for SQLite. | DONE |
| **backend/app/deps.py** | YES | 🔧 YES | `require_role` (line 175) now raises 403 with a string detail `Role '<role>' is not permitted. Required: [...]` matching the `{"detail": "<string>"}` contract. `test_protected_route_with_wrong_role_returns_403` + 9 others pass. | CLOSED |
| **backend/app/security.py** | YES | YES | bcrypt cost from `settings.BCRYPT_COST`; refresh token has **no** role claim (§9); `decode_token(token, expected_type=...)` enforces the `type` claim (deps uses `access`, auth uses `refresh`); access token carries role (required by ws auth). | DONE |
| **backend/app/exceptions.py** | YES | 🔧 YES | `AppError`, `InvalidStateTransition`, `error_response` all defined; `InvalidStateTransition` is now raised by `services/verification.py` and `api/hotlist.py`, so the registered 409 handler in `main.py` is live (previously dead code). | CLOSED |
| **backend/app/models/** (user, device, complaint, hotlist, sighting, audit_log, mixins, `__init__`) | YES | YES | All columns match §5. `TimestampMixin` exists and all six models inherit it. `LEGAL_TRANSITIONS` + `is_legal_transition()` correct. `audit_log.actor_id` nullable (system actions). | DONE |
| **backend/app/schemas/auth.py** | YES | YES | `SafeEmail` regex (allows `.local`), role whitelist via `Role` enum, min password 8, `extra="forbid"`. `TokenResponse` defined but currently unused (auth.py uses local response models). | DONE |
| **backend/app/schemas/sighting.py** | YES | 🔧 YES | `SightingIngestResponse.reasons: list[dict]` now matches the pipeline (API builds `{"index","reason"}` items). `SightingEvent.plate` relaxed from strict `_PLATE_REGEX` to raw OCR (max 20 chars) — server normalises (§6), so malformed OCR drops as `plate_not_hotlisted` instead of 422. | CLOSED |
| **backend/app/schemas/complaint.py** | YES | YES | Indian plate regex, `extra="forbid"`, length bounds. | DONE |
| **backend/app/schemas/user.py** | YES | YES | Pagination bounds (per_page ≤ 100), `from_attributes`. | DONE |
| **backend/app/schemas/audit.py** | YES | YES | `from_attributes`, matches admin router. | DONE |
| **backend/app/schemas/device.py** | YES | YES | `DeviceRegisterResponse{device_id, device_token, encryption_key_b64}` matches mobile `device.ts`. | DONE |
| **backend/app/api/auth.py** | YES | 🔧 YES | Contract restored. register → `{user, tokens:{access_token, refresh_token, token_type}}`; login → top-level `{access_token, refresh_token, token_type}` + `user`; refresh accepts `{refresh_token}` body (cookie fallback `rakshak_refresh`), returns `{access_token, refresh_token}` and re-sets the cookie. `TokenResponse` imported from `schemas/auth`. All 7 `test_auth.py` tests pass. | CLOSED |
| **backend/app/api/complaints.py** | YES | YES | Rate limits (user=3/ip=10 per 86400s per key), multipart proof upload, verification delegated to the `verification` service. `notes` field accepted but not persisted (limitation #7). | DONE |
| **backend/app/api/devices.py** | YES | YES | Register → 201 with device_id/device_token/encryption_key_b64; revoke; bcrypt-hashed device tokens; `wrap_key_for_device`. Key versioning matches `derive_device_key(..., 0)`. Step 4 added proofs: token stored bcrypt-hashed (never plaintext), credentials returned exactly once and never echoed by sync/revoke responses. | DONE |
| **backend/app/api/hotlist.py** | YES | 🔧 YES | COP-only module guard, legal transitions → 409, encrypted sync response, detail sightings capped at 50 newest-first. Phase 7: detail sightings now expose `photo_url` for dashboard thumbnails (`test_detail_sightings_include_photo_url`). | CLOSED |
| **backend/app/api/sightings.py** | YES | 🔧 YES | `_process_event_batch` emits one `{"index", "reason"}` dict per dropped event (schema-valid, no plate echo). Plates that fail OCR format (incl. empty string, which previously 500'd — Step 5 fix) are dropped as `plate_not_hotlisted` rather than 422/500. All `test_sightings.py` (8) + `test_privacy.py` (7) pass. | CLOSED |
| **backend/app/api/analytics.py** | YES | YES | All 6 endpoints, COP-only, `from`/`to` aliases, Python bucketing so identical SQL runs on SQLite and PG. Step 7 added tests for the `recovery-metrics` weekly series and the `from`/`to` window aliases. | DONE |
| **backend/app/api/admin.py** | YES | YES | Users list (role filter, pagination), role change + audit log, audit listing. | DONE |
| **backend/app/api/ws.py** | YES | PARTIAL | `/ws/dashboard` JWT query auth (COP/ADMIN only), 30s ping, in-memory `ConnectionManager` (multi-worker broadcast gap — limitation #11). | MED |
| **backend/app/api/detect.py** | YES | PARTIAL | Prototype fallback that accepts raw camera frames — violates the zero-retention promise if used in production; documented (limitation #2). | MED |
| **backend/app/services/verification.py** | YES | 🔧 YES | FIR deadline reads `settings.FIR_DEADLINE_HOURS`; `verify_complaint` validates the decision first (ValueError → 400), then raises `InvalidStateTransition(from, to)` for non-pending complaints (→ 409). | CLOSED |
| **backend/app/services/dedup.py** | YES | YES | Redis throttle (30s device+plate) + cluster window (±90s same hotlist_id → same cluster_id), matching §6 line 134. | DONE |
| **backend/app/services/crypto.py** | YES | YES | HKDF-SHA256 per-device key derivation, AES-256-GCM encrypt/decrypt, key wrapping. `test_crypto.py` round-trips pass. Step 4 added tamper-detection tests: single bit-flip in **ciphertext** or **IV** → `InvalidTag`. | DONE |
| **backend/app/services/storage.py** | YES | YES | `StorageBackend` protocol + `LocalFileSystemBackend` under `settings.UPLOAD_DIR`, `get_storage()` factory. S3 backend deferred (limitation #12). | DONE |
| **backend/app/services/normalizer.py** | YES | YES | §8 position-aware OCR corrections + `is_valid_plate`. | DONE |
| **backend/app/services/notifier.py** | YES | YES | Payload builders + `push_*` + `schedule()` with loop binding (drops safely under test transport). | DONE |
| **backend/app/services/scheduler.py** | YES | 🔧 YES | §10 now fully implemented (Step 6): sightings > 90d purge **with photos** (row deletion first, then best-effort blob delete), rejected complaints > 30d, hotlist > 180d after cooldown, audit logs > 1y. `purge_old_data(db=None, storage=None)` is injectable for tests; `tests/test_retention.py` (4) covers every boundary. | CLOSED |
| **backend/app/services/audit.py** | YES | YES | Durable privileged-mutation trail (extra module beyond §7 tree, needed). | DONE |
| **backend/app/services/matching.py** | MISSING | — | Hotlist matching lives inline in `api/sightings.py` as `_find_active_hotlist`. Behaviour correct; file boundary differs from spec tree. | MED |
| **backend/app/services/__init__.py** | YES | YES | Package marker. | DONE |
| **backend/tests/conftest.py** | YES | PARTIAL | SQLite + FakeRedis; fixtures `client`, `db_session`, `citizen_headers`, `cop_headers`, `_auth_headers`. No ADMIN/VOLUNTEER header fixtures. | LOW |
| **backend/tests/test_auth.py** | YES | 🔧 YES | 7/7 pass after the `auth.py` body-token contract fix. Tests were the contract. | CLOSED |
| **backend/tests/test_sightings.py** | YES | 🔧 YES | 8/8 pass once `reasons` items are `{"index","reason"}` dicts (reasons-validation 500 removed). | CLOSED |
| **backend/tests/test_privacy.py** | YES | 🔧 YES | 7/7 pass once response and schema align: raw OCR plates (e.g. `KA05ZZ432L`) drop as unmatched with no echo, no row, no log; positive path persists and logs; Step 5 added empty-plate 200-drop and mixed-batch isolation. | CLOSED |
| **backend/tests/test_seed_db.py** | NEW | YES | Added Step 2: 3 tests proving `seed_users` / `seed_demo_hotlist` run twice with zero net effect (idempotent). | DONE |
| **scripts/seed_db.py** | YES | YES | Idempotency now verified by `test_seed_db.py` (exists-by-email skip + exists-by-plate skip). Still not a true upsert — acceptable for demo. | CLOSED |
| **backend/tests/test_crypto.py / test_device_sync.py / test_complaints.py / test_hotlist.py / test_admin.py / test_analytics.py / test_health.py / test_fir_expiry.py / test_plate_regex.py / test_rate_limit.py** | YES | YES | In the 115 passing baseline. | DONE |
| **backend/tests/test_matching.py** | MISSING | — | No dedicated tests for `_find_active_hotlist` / the ingest pipeline matching path. | MED |
| **backend/tests/test_dedup.py** | MISSING | — | Throttle + clustering covered only indirectly through `test_sightings.py`. | MED |
| **dashboard/src/lib/auth.tsx** | YES | YES | Access token held in memory only (§9). | DONE |
| **dashboard/src/lib/api.ts** | YES | YES | Posts `{refresh_token}` in body, `credentials:"include"`, one retry on 401. Matches the intended contract (needs the `auth.py` fix to function). | DONE |
| **dashboard/src/pages/Login.tsx** | YES | 🔧 YES | Expects top-level `{access_token, refresh_token, token_type}` and role-based redirect — matches the Phase 1 `auth.py` contract; verified by `test_auth.py` + `tsc`. | CLOSED |
| **dashboard/src/pages/Register.tsx** | YES | 🔧 YES | Expects `data.tokens.access_token` — matches the Phase 1 `auth.py` register shape (`{user, tokens}`); verified by `test_auth.py` + `tsc`. | CLOSED |
| **dashboard/src/lib/ws.ts** | YES | PARTIAL | No missed-event replay on reconnect (limitation #11). | MED |
| **dashboard/src/pages/PoliceVehicleDetail.tsx** | YES | 🔧 YES | Phase 7 hardening: sightings table now renders a lazy-loaded `photo_url` thumbnail (backend detail payload exposes it; WS `new_sighting` already carried it). | CLOSED |
| **dashboard/src/pages/AdminPanel.tsx** | YES | 🔧 YES | Phase 7 hardening: users + audit tables now paginate (prev/next, page indicator); role filter resets to page 1. Was hardcoded to page 1. | CLOSED |
| **mobile/src/services/api.ts** | YES | YES | Body refresh + one retry; consumes the Phase 1 auth contract (`{refresh_token}` body, top-level tokens). Phase 8: runtime verified — `tsc --noEmit` clean. | DONE |
| **mobile/src/services/device.ts** | YES | YES | Registers a VOLUNTEER device, stores device id/token/encryption key. | DONE |
| **mobile/src/services/hotlist.ts** | YES | YES | On-device in-memory hotlist set, 15-min sync, plaintext never written to disk, state cleared on device revocation (§3.1). | DONE |
| **mobile/src/ai/match.ts** | YES | YES | Pure normalise + hotlist matching with Jest tests (`match.test.ts`). | DONE |
| **mobile/src/ai/inference.ts** | YES | PARTIAL | TFLite fallback → backend `POST /api/v1/detect` (limitation #1). | MED |
| **mobile/src/store/auth.ts** | YES | PARTIAL | Access token also persisted to SecureStore — §9 wants memory-only (limitation #3). | MED |
| **mobile/src/services/queue.ts / hitHistory.ts** | YES | PARTIAL | Offline hit queue + persistent hit history (limitation #36). Phase 8 fix: `classifyDelivery` now reconciles the post-Phase 1 ingest `reasons: [{index, reason}]` shape (was misreading it as `string[]`, so throttled hits showed as ``rejected``); 4 new Jest tests lock it. | MED |
| **scripts/device_simulator.py** | YES | YES | Full Flow C pipeline (quality filter → YOLO → OCR → normalise → temporal voting → hotlist match → hit queue/flush). Phase 9: minimal runtime installed (numpy/opencv-headless/requests); now importable and covered by 15 unit tests. | DONE |
| **scripts/download_sample_videos.sh / run_demo.sh / audit_docstrings.py / Makefile / start_demo.sh** | YES | YES | All present and internally consistent. | DONE |
| **data/samples/** | MISSING | — | Simulator video input; download script reaches public URLs but githubusercontent/raw sources are unreachable in this env (limitation #56). Non-blocking; full demo requires a Docker-capable host anyway. | LOW |
| **backend/alembic/versions/** | YES | PARTIAL | PG-specific migrations (raw enums, UUID, TIMESTAMPTZ, PostGIS); **4 revision heads**; cannot run locally (no Docker) — unverified against real Postgres. | MED |

## Cross-cutting gaps (all confirmed this step)

| Gap | Severity | Detail |
|---|---|---|
| Auth token contract | 🔧 CLOSED | Fixed in Phase 1 (`api/auth.py`); verified by `test_auth.py` 7/7 + dashboard/mobile api layers already consume the fixed shapes. |
| `require_role` object detail | 🔧 CLOSED | Fixed in Phase 1 (`deps.py`); string detail, `test_protected_route_with_wrong_role_returns_403` green. |
| Sighting `reasons` type | 🔧 CLOSED | Fixed in Phase 1 (`api/sightings.py` + `schemas/sighting.py`); every ingest returns `reasons: [{index, reason}]`; privacy + sightings suites green. |
| Data retention §10 | 🔧 CLOSED | Step 6 (`services/scheduler.py`) now implements the full §10 policy: sightings > 90d purge **with photos**, rejected complaints > 30d, hotlist > 180d after cooldown, audit logs > 1y. `tests/test_retention.py` (4) covers every boundary with an injectable session + fake storage. |
| `InvalidStateTransition` dead | 🔧 CLOSED | Now raised by `services/verification.py` (Step 3) and `api/hotlist.py` `_apply_status_update`; `test_reverify_verified_complaint_returns_409` plus the existing hotlist 409 tests are green. |
| Device-token lookup | LOW | `_match_device_token` linearly bcrypt-verifies every device row per request; O(n) per ingest. |
| Hotlist plates in logs | LOW | `scheduler.py` logs `plate=entry.plate`; acceptable for hotlisted entries but keep out of non-hotlist paths. |

## Summary statistics

| Category | Count |
|---|---|
| Matches contract (YES / 🔧 YES) | 46 |
| Partial | 9 |
| Not matching (NO) | 0 |
| Missing entirely | 4 |
| **Total rows** | **59** |

> Counts reconciled in the Phase 10 final pass by parsing the file table
> directly (Python, UTF-8): 31 plain YES + 15 `🔧 YES` + 9 PARTIAL +
> 4 MISSING (`—` verdict column) = 59 rows. Earlier figures (56) were a
> hand count that missed three rows added in later phases.

## Baseline measurements (Phase 0 → Phase 9)

| Check | Phase 0 | Phase 1 | Phase 2 | Phase 3 | Phase 4 | Phase 5 | Phase 6 | Phase 7 | Phase 8 | Phase 9 (this step) |
|---|---|---|---|---|---|---|---|---|---|---|
| `pytest -q` (backend, SQLite + FakeRedis, `backend\.venv`) | **115 passed, 13 failed** | **131 passed, 0 failed** | **132 passed, 0 failed** | **136 passed, 0 failed** | **138 passed, 0 failed** | **142 passed, 0 failed** | **144 passed, 0 failed** | **145 passed, 0 failed** | **145 passed, 0 failed** | **160 passed, 0 failed** |
| Failures by file @ Phase 0 | auth 6, privacy 4, sightings 3 | — | — | — | — | — | — | — | — | — |
| `scripts/audit_docstrings.py backend scripts` | — | **0 violations** (66 files) | **0 violations** (66 files) | **0 violations** (66 files) | **0 violations** (66 files) | **0 violations** (67 files) | **0 violations** (67 files) | **0 violations** (67 files) | **0 violations** (67 files) | **0 violations** (68 files) |
| Dashboard `tsc --noEmit` / `npm run build` | **impossible** (no `node_modules`) | same | same | same | same | same | same | **PASS / PASS** (deps installed Phase 7) | unchanged | unchanged |
| Mobile `tsc --noEmit` / `jest` | **impossible** (no `node_modules`) | same | same | same | same | same | same | same | **PASS / 26 passed, 0 failed** (deps installed Phase 8) | unchanged |
| Simulator import / `--help` | **impossible** (no cv2) | same | same | same | same | same | same | same | same | **PASS** (numpy/opencv-headless/requests installed Phase 9) |
| New tests added | — | `test_seed_db.py` (3) | `test_complaints.py` (1) | `test_crypto.py` (2) + `test_device_sync.py` (2) | `test_privacy.py` (2: empty-plate 200-drop, mixed-batch isolation) | `test_retention.py` (4: sightings+photos 90d, audit 1y, rejected 30d, hotlist 180d) | `test_analytics.py` (2: recovery-metrics weekly series, `from`/`to` window alias) | `test_hotlist.py` (1: detail sightings expose `photo_url`) | `queue.test.ts` (4: ingest `reasons` classification) | `test_device_simulator.py` (15: normalise, quality filter, temporal voting, JPEG, queue flush) |
| `docker compose up` / `alembic upgrade head` | **impossible** (no Docker/WSL on this host) | still impossible | still impossible | still impossible | still impossible | still impossible | still impossible | still impossible | still impossible | still impossible |
| Spec authority | `docs/PROJECT_INFO.md` only | unchanged | unchanged | unchanged | unchanged | unchanged | unchanged | unchanged | unchanged | unchanged |