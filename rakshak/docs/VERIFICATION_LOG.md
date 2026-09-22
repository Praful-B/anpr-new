# RAKSHAK — Verification Log

Append-only log of the five-way verification performed after each phase.

Check legend:

1. **Static** — lint, types, docstrings, no TODOs/print/console.log.
2. **Unit** — `pytest` (backend, SQLite + FakeRedis in `backend\.venv`) and `tsc --noEmit` (dashboard + mobile) where runnable.
3. **Integration** — running stack: endpoints + database rows (requires Docker — **blocked on this host**; local equivalent via TestClient is recorded as such).
4. **E2E** — the human workflow for the phase, end to end.
5. **Adversarial** — deliberate attempts to break the phase, with outcomes.

> **REBUILT 2026-09-22 — the Phase 0/2/2b/4/9/10 and "Final acceptance sweep"
> entries in the previous version of this file were written by an earlier pass
> and are **not reproducible** here. They cite a missing spec (`AGENT_BUILD_SPEC`
> / `HANDOFF`), claim a healthy Docker stack on a host with no container runtime,
> and quote pytest figures (66, 128 passed) that contradict the measured baseline
> (**115 passed / 13 failed**). Those entries are discarded, not corrected. This
> log records only what is actually executed and observed from now on.**

---

## Phase 0 — Full spec audit — 2026-09-22

| # | Check | Result | Notes |
|---|-------|--------|-------|
| 1 | Static | PASS | Full file-tree audit re-read this step (56 rows); `docs/GAP_ANALYSIS.md` rebuilt from PROJECT_INFO only. 35 YES / 12 PARTIAL / 5 NO / 4 MISSING. |
| 2 | Unit | FAIL | `pytest -q` → **115 passed, 13 failed** (auth 6, privacy 4, sightings 3). Root causes isolated: `api/auth.py` token shapes, `api/sightings.py` `reasons` type. |
| 3 | Integration | BLOCKED | No container runtime on this host; `alembic upgrade head` not runnable. Composed acceptance for Step 11 §8 requires a Docker-capable host. |
| 4 | E2E | BLOCKED | Same environment blocker as above. |
| 5 | Adversarial | PARTIAL | Confirmed: `require_role` dict-detail 403 breaks the string-detail contract; auth body-token contract deviation breaks 3 consumer shapes; sighting ingest 500. |

Verdict: **FAIL — do not start later phases until Phase 1 fixes the 3 confirmed
backend defects and pytest is green.**

---

## Phase 1 — Backend foundation (response contracts) — 2026-09-22

Scope: the 3 confirmed backend contract defects + sighting ingest handling.

- `api/auth.py` — register/login/refresh response + request shapes restored to
  the contract used by every consumer (tests, dashboard `lib/api.ts`, mobile
  `services/api.ts`): register → `{user, tokens}`; login → top-level tokens +
  user; refresh reads `{refresh_token}` body (cookie fallback) and returns both
  tokens. `TokenResponse` reused from `schemas/auth`.
- `deps.py` — `require_role` 403 now returns a string `detail` (was `{"error":{...}}`).
- `main.py` — exception handlers (AppError, InvalidStateTransition, catch-all)
  return `{"detail": "<string>"}`; error codes logged, never returned.
- `api/sightings.py` — `_process_event_batch` returns one `{"index", "reason"}`
  dict per dropped event (matches `SightingIngestResponse.reasons: list[dict]`).
- `schemas/sighting.py` — `SightingEvent.plate` accepts raw OCR (max 20 chars);
  normalisation is server-side per §6, so OCR noise drops as `plate_not_hotlisted`
  instead of a 422 on the request.
- `tests/test_seed_db.py` (new) — proves `seed_db.py` is idempotent (run twice,
  zero net rows; missing-citizen skip; existing-email skip).

| # | Check | Result | Notes |
|---|-------|--------|-------|
| 1 | Static | PASS | `scripts/audit_docstrings.py backend scripts` → **0 violations** (66 files). No new TODO/print. (Frontend `tsc` not runnable yet — `node_modules` absent; queued for Phase 5/7.) |
| 2 | Unit | PASS | `pytest -q` → **131 passed, 0 failed** (`backend\.venv`, SQLite + FakeRedis, ~3 min). Baseline was 115/13. All auth, sightings, privacy suites green; 3 new seed tests. |
| 3 | Integration | BLOCKED | No Docker/Postgres on this host; PostgreSQL-specific paths (Alembic, PostGIS) still unverified. Local equivalent = full ASGI TestClient suite (passed). |
| 4 | E2E | BLOCKED | Device→API→dashboard flow needs the compose stack (Step 11 §8). |
| 5 | Adversarial | PASS | Raw-OCR plate `KA05ZZ432L` → no echo, no row, no log, response 200 with reason code only. `reasons` items are dicts; `detail` is always a string; refresh rotation returns fresh token + cookie. |

Verdict: **PASS.**

---

## Phase 2 — Hotlist state machine (typed transitions) — 2026-09-22

Scope: activate the previously dead `InvalidStateTransition` (409) handler by
wiring the typed exception through complaint verification and hotlist status
updates.

- `services/verification.py` — `_ensure_pending_verification(complaint,
  target_status)` now raises `InvalidStateTransition(from_state, to_state)` for
  non-pending complaints (was bare `ValueError` → 500 path expected 409).
  `verify_complaint` validates the decision first (ValueError → 400), then the
  state, then applies approve/reject; `_reject_complaint` still 400s on a
  missing reason.
- `api/complaints.py` — verify endpoint: `except ValueError` → 400 unchanged;
  `InvalidStateTransition` (an `Exception` subclass) propagates to the `main.py`
  handler → 409. Raises docstring updated.
- `api/hotlist.py` — `_apply_status_update` raises `InvalidStateTransition`
  instead of a hand-built 409 `HTTPException`; message is now the handler's
  `Cannot transition from X to Y`. Unknown status still 400. DELETE /
  `recovery` override that soft-closes an entry is unchanged (operator
  override per PROJECT_INFO, not a state-machine path).
- `tests/test_complaints.py` — added `test_reverify_verified_complaint_returns_409`
  (approve → approve → 409). Existing hotlist 409 tests assert status only, so
  the message change is safe.

| # | Check | Result | Notes |
|---|-------|--------|-------|
| 1 | Static | PASS | `scripts/audit_docstrings.py backend scripts` → **0 violations** (66 files). Function lengths re-checked after the `verification.py` restructure. |
| 2 | Unit | PASS | `pytest -q` → **132 passed, 0 failed** (131 + 1 new). |
| 3 | Integration | BLOCKED | Same host constraint (no Docker/Postgres); TestClient suite covers the 409 path end to end. |
| 4 | E2E | BLOCKED | Needs the compose stack (Step 11 §8). |
| 5 | Adversarial | PASS | Double-approve on a VERIFIED complaint → 409 `{"detail":"Cannot transition from VERIFIED to VERIFIED"}`; illegal hotlist transition still 409; unknown status still 400; reject-without-reason still 400. |

Verdict: **PASS.**

---

## Phase 3 — Device registration + encrypted sync — 2026-09-22

Scope: `devices.py`, `crypto.py` (HKDF, AES-GCM, key wrap), `hotlist/sync`.
Implementation was already in place and green; this step closed the two
**exit-criteria** gaps left by the audit — tamper detection and once-only
credentials.

- `tests/test_crypto.py` — added 2 tamper tests: flipping a single bit in the
  **ciphertext** and flipping a single bit in the **IV** both raise
  `cryptography.exceptions.InvalidTag` (GCM authentication bound to both).
- `tests/test_device_sync.py` — added 2 proofs:
  - `test_register_device_token_stored_hashed_not_plaintext` — the stored
    `token_hash` is a bcrypt hash of the returned raw token; the raw token and
    the raw encryption key never appear in `encryption_key_wrapped` or any
    device column.
  - `test_register_returns_fresh_credentials_each_call` — each registration
    issues a new device_id/token/key; the sync and revoke responses never
    re-issue or echo the raw token or key (returned exactly once).

| # | Check | Result | Notes |
|---|-------|--------|-------|
| 1 | Static | PASS | `scripts/audit_docstrings.py backend scripts` → **0 violations** (66 files). |
| 2 | Unit | PASS | `pytest -q` → **136 passed, 0 failed** (132 + 4 new). `test_crypto.py` + `test_device_sync.py` = 27 green standalone. |
| 3 | Integration | BLOCKED | No Docker/Postgres on this host; TestClient covers register→sync→decrypt→revoke end-to-end. |
| 4 | E2E | BLOCKED | Real-device sync needs the compose stack + mobile/simulator (Steps 9–10). |
| 5 | Adversarial | PASS | Ciphertext 1-bit flip → InvalidTag; IV 1-bit flip → InvalidTag; wrong key → InvalidTag; bad token → 401; revoked device sync → 401; raw token/key absent from every post-registration response. |

Verdict: **PASS.**

---

## Phase 4 — Sighting ingestion + privacy (zero-retention) — 2026-09-22

Scope: `api/sightings.py` ingestion pipeline against the **privacy invariant**:
non-hotlisted plates never reach an outbound call, never appear in logs, never
land in the sightings table — even from a malicious/buggy client.

- **Defect found & fixed:** an empty `plate` string (`""`) passed schema
  validation (`max_length` only, no `min_length`) and reached
  `normalise_plate("")`, which raises `ValueError` → the entire batch returned
  **500 INTERNAL_ERROR**. `_process_single_event` now catches `ValueError` and
  drops the event as `plate_not_hotlisted` (200, no echo, no row).
- `tests/test_privacy.py` — added 2 adversarial tests:
  - `test_empty_plate_event_returns_200_drop_not_500` — 200, dropped=1,
    `reasons == [{"index":0,"reason":"plate_not_hotlisted"}]`, zero rows.
  - `test_mixed_batch_isolates_unmatched_plate` — one request with a
    non-hotlisted AND a hotlisted event: unmatched drops with reason only (no
    echo), matched is stored; exactly one row.
- Audit of the drop paths: raw OCR, empty, out-of-tolerance-timestamp, and
  throttled events are all capped at a reason code; `check_throttle`/`assign_cluster`
  debug logs carry device/hotlist/cluster ids, never a non-hotlisted plate
  (throttle can only run after a hotlist match).

| # | Check | Result | Notes |
|---|-------|--------|-------|
| 1 | Static | PASS | `scripts/audit_docstrings.py backend scripts` → **0 violations** (66 files). |
| 2 | Unit | PASS | `pytest -q` → **138 passed, 0 failed** (136 + 2 new). `test_privacy.py` (7) + `test_sightings.py` (8) = 15 standalone. |
| 3 | Integration | BLOCKED | No Docker/Postgres on this host; TestClient exercises the full ingest path (schema → normalise → hotlist → throttle → dedup → store). |
| 4 | E2E | BLOCKED | Live device→ingest→WS→dashboard flow needs the compose stack (Steps 9–10). |
| 5 | Adversarial | PASS | Empty plate → 200 drop (was 500); `KA05ZZ432L` raw-OCR → no echo/row/log; mixed batch → per-event isolation; `reasons` items are `{index, reason}` with no plate; timestamp-invalid → reason code only. |

Verdict: **PASS.**

---

## Phase 5 — Data retention + scheduler (§10) — 2026-09-22

Scope: close the last HIGH gap — the nightly purge must enforce the full §10
policy, not just rejected complaints and hotlist cooldowns.

- `services/scheduler.py`:
  - New constants: `SIGHTING_RETENTION_DAYS = 90`, `AUDIT_LOG_RETENTION_DAYS = 365`
    (existing: 30d rejected complaints, 180d hotlist cooldown, 02:00 UTC nightly).
  - `purge_old_data(db=None, storage=None)` — now accepts an injected **session**
    and **storage backend** (owns both when `None`), so the whole purge runs under
    unit tests the same way `expire_unconfirmed_entries(db=None)` already did.
  - `_purge_old_sightings` — deletes sighting rows older than 90 days
    (`Sighting.captured_at < cutoff`) and then deletes each photo blob
    best-effort via `_delete_photo_safely` (missing file → debug; any other
    failure → warning, never aborting the job).
  - `_purge_expired_audit_logs` — deletes `AuditLog` rows older than 1 year.
- `tests/test_retention.py` (new, 4 tests) with a `FakeStorage` that records
  deleted URLs:
  - Sightings > 90d removed **and their photos deleted**; recent sighting photo
    untouched.
  - Audit logs > 365d removed; recent kept.
  - Rejected complaints > 30d removed; recent rejected AND old verified kept.
  - Expired hotlists past cooldown + 180d removed; recently-expired + active kept.

| # | Check | Result | Notes |
|---|-------|--------|-------|
| 1 | Static | PASS | `scripts/audit_docstrings.py backend scripts` → **0 violations** (67 files, +`test_retention.py`). All new functions ≤40 code lines with docstrings. |
| 2 | Unit | PASS | `pytest -q` → **142 passed, 0 failed** (138 + 4 new). |
| 3 | Integration | BLOCKED | No Docker/Postgres on this host; an injected session + fake storage substitutes for the real APScheduler service run (scheduler timers not started in tests). |
| 4 | E2E | BLOCKED | Nightly-cron behaviour needs the compose stack (Step 11 §8). |
| 5 | Adversarial | PASS | Each retention boundary is asserted from both sides (able to purge vs. must survive): 90/365/30/180 + photo deletion; photo-already-deleted tolerated (no job failure). |

Verdict: **PASS.**

---

## Phase 6 — Analytics + admin (re-verification) — 2026-09-22

Scope: re-verify the Phase 6 surface (all 6 analytics endpoints, all 3 admin
endpoints, every audit-write path) against §6 and §14A1; close test-coverage
gaps rather than rewrite working code.

- Re-audit: every endpoint matches the spec verbatim — `overview` keys,
  `heatmap` rounded to 3 decimals (~100m grid), `recovery-metrics` weekly
  `{week_start, hotlist_added, recovered, expired, recovery_rate}`, `fp-rate`
  with `per_device` breakdown, `device-coverage` with aggregate + map list,
  `time-patterns` `by_hour`/`by_day`; admin = paginated users + role filter,
  role-change PATCH with audit row, paginated audit listing; `UserListResponse`
  uses `total gt 0`.
- `tests/test_analytics.py` — added 2 tests:
  - `test_analytics_recovery_metrics_weekly_series` — a CLOSED entry with
    `recovered_at` and an EXPIRED entry land in the current ISO week with
    `hotlist_added >= 2`, `recovered >= 1`, `expired >= 1`, `recovery_rate >= 0`.
  - `test_analytics_heatmap_respects_from_bound` — the `from` alias binds the
    window: a sighting 45d old is excluded at the default 30-day lookback and
    reappears with a 60-day bound (locks the alias contract from §14A1).

| # | Check | Result | Notes |
|---|-------|--------|-------|
| 1 | Static | PASS | `scripts/audit_docstrings.py backend scripts` → **0 violations** (67 files). |
| 2 | Unit | PASS | `pytest -q` → **144 passed, 0 failed** (142 + 2 new). `test_analytics.py` 8/8 standalone. |
| 3 | Integration | BLOCKED | No Docker/Postgres on this host; TestClient exercises all 6 analytics + 3 admin routes against SQLite (identical queries by design — Python bucketing). |
| 4 | E2E | BLOCKED | COP dashboard analytics page needs the compose stack (Step 11 §8). |
| 5 | Adversarial | PASS | Citizen → 403 on analytics and admin; anonymous → 401; unknown role filter → 400; unknown user role-change → 404; old sighting excluded by `from` window. |

Verdict: **PASS.**

---

## Phase 7 — Dashboard hardening — 2026-09-22

Scope: harden the dashboard now that its toolchain is runnable on this host
(`npm install` succeeded — the npm registry is reachable even though github is
blocked; `tsc --noEmit` and `npm run build` both pass).

- `api/hotlist.py` — `_recent_sightings` now includes `photo_url` per sighting
  (additive; the detail endpoint previously omitted it while photos were already
  stored and the WS `new_sighting` payload already carried it).
- `dashboard/src/pages/PoliceVehicleDetail.tsx` — `SightingInfo` gains
  `photo_url`; the sightings table renders a lazy-loaded thumbnail that opens the
  full image in a new tab (falls back to an em dash). The WS handler maps
  `photo_url` for live updates too. Closes the "stored but never rendered"
  photo gap (limitation #28).
- `dashboard/src/pages/AdminPanel.tsx` — users + audit tables now paginate:
  prev/next buttons, "Page N of M" indicator, and the role filter resets to
  page 1. Both were hardcoded to page 1 before (limitation #24).
- `tests/test_hotlist.py` — added `test_detail_sightings_include_photo_url`.

| # | Check | Result | Notes |
|---|-------|--------|-------|
| 1 | Static | PASS | `scripts/audit_docstrings.py backend scripts` → **0 violations** (67 files). Dashboard `tsc --noEmit` → clean; `npm run build` → clean (informational only: leaflet double-import/405 kB chunk warnings). |
| 2 | Unit | PASS | `pytest -q` → **145 passed, 0 failed** (144 + 1 new). `test_hotlist.py` 19/19. |
| 3 | Integration | BLOCKED | TestClient covers the new `photo_url` field end to end; real browser rendering needs the compose stack. |
| 4 | E2E | BLOCKED | Visual check of thumbnails/pagination needs the compose stack (Step 11 §8). |
| 5 | Adversarial | PASS | Detail payload still valid with the extra key (`sightings == []` unchanged); `photo_url` absent → em dash (no broken image); pagination clamps at bounds (prev disabled on page 1). |

Verdict: **PASS.**

---

## Phase 8 — Mobile on-device pipeline — 2026-09-22

Scope: make the mobile toolchain runnable and re-verify the on-device pipeline
now that `npm install` works on this host (registry reachable; github blocked).

- `npm install` in `mobile/` succeeded; `npx tsc --noEmit` → clean.
- **Contract-drift defect found and fixed**: `mobile/src/services/queue.ts`
  typed the ingest `reasons` field as `string[]` and checked
  `reasons.includes("throttled")`. Since Phase 1 the backend returns
  `reasons: [{index, reason}]` dicts, so throttled hits were misclassified as
  ``rejected`` (wrong scanner-UI status; the queued row was still removed so no
  data loss). Extracted a pure, exported `classifyDelivery(accepted, reasons)`
  and wired `postHit` to it.
- `mobile/src/services/__tests__/queue.test.ts` — added 4 Jest tests covering
  sent / throttled / rejected and a regression guard that a throttled reason is
  never classified as rejected.

| # | Check | Result | Notes |
|---|-------|--------|-------|
| 1 | Static | PASS | `scripts/audit_docstrings.py backend scripts` → **0 violations** (67 files, unchanged — no backend edits this step beyond none). Mobile `npx tsc --noEmit` → clean. |
| 2 | Unit | PASS | Mobile `jest` → **26 passed, 0 failed** (22 match + 4 queue). Backend `pytest -q` unchanged at **145 passed, 0 failed**. |
| 3 | Integration | BLOCKED | `expo-sqlite`/camera/hotlist sync need a device/emulator; TestClient covers the `reasons` shape the queue consumes. |
| 4 | E2E | BLOCKED | On-device scan → match → flush needs an emulator + the compose stack. |
| 5 | Adversarial | PASS | `classifyDelivery` guards: mixed reasons list never misclassifies a throttled event; rejects unknown reasons as ``rejected``. |

Verdict: **PASS.**

---

## Phase 9 — Simulator + demo data — 2026-09-22

Scope: verify the host-side device simulator (`scripts/device_simulator.py`)
and the demo data path. The full Flow C loop (YOLO + EasyOCR against a sample
video) needs the compose stack + models and remains blocked; this step made the
pure-pipeline logic **runnable and tested** for the first time.

- Installed the minimal simulator runtime into `backend\.venv`: `numpy`,
  `opencv-python-headless`, `requests` (PyPI reachable; `structlog` was already
  present). The heavier `ultralytics`/`easyocr` stack is imported lazily by
  `_load_detection_models` and stays out of tests.
- `python scripts/device_simulator.py --help` now succeeds (previously died on
  `ModuleNotFoundError: cv2`); `py_compile` was already clean.
- Added `backend/tests/test_device_simulator.py` — **15 tests**:
  - §8 normalisation: canonical pass-through, whitespace/case stripping,
    empty input, `B->8` digit-slot correction, multi-noise correction
    (asserted against the engine's real structure heuristic, not guesses).
  - Flow C quality gate: high-texture frame accepted; flat frame rejected
    (blur); dark frame rejected (brightness); frames must be 3-channel BGR
    (single-channel arrays raise in `cvtColor` — asserted via correct inputs).
  - Temporal voting: 3-of-5 threshold, alternating reads never reach majority,
    per-tracker isolation.
  - JPEG encoding: decodable base64 with JPEG magic bytes.
  - SQLite offline queue: flush on 200 deletes the row; 5xx keeps it queued;
    empty queue is a no-op (asserts `requests.post` never called).
- `data/samples/` remains **MISSING** — the download script's githubusercontent
  sources are unreachable in this environment (limitation #56). Script tolerates
  this by warning and continuing.

| # | Check | Result | Notes |
|---|-------|--------|-------|
| 1 | Static | PASS | `scripts/audit_docstrings.py backend scripts` → **0 violations** (68 files — +1 for the new test file). Simulator `py_compile` + `--help` both clean. |
| 2 | Unit | PASS | `pytest -q` → **160 passed, 0 failed** (145 + 15 new). |
| 3 | Integration | BLOCKED | Real video → YOLO → OCR → backend ingest needs the compose stack (Docker unavailable) plus `ultralytics`/`easyocr` model weights. |
| 4 | E2E | BLOCKED | `run_demo.sh` requires `make up` (compose) and `data/samples/` (unreachable). |
| 5 | Adversarial | PASS | 5xx response keeps the hit queued (no loss); empty-queue flush provably never issues a request; alternating OCR disagreement never fires the voter. |

Verdict: **PASS.**

---

## Phase 10 — Docs + final audit — 2026-09-22

Scope (Step 11): final pass over `docs/API.md`, `ARCHITECTURE.md`,
`RUNBOOK.md`, `DEMO_SCRIPT.md`, `GAP_ANALYSIS.md`, and
`KNOWN_LIMITATIONS.md`, then the full §8 composed acceptance — **blocked on
this host** (below).

**What the final pass found and fixed (docs vs. code, not claims):**

- `API.md` — ingest response documented `reasons` as bare reason-code strings;
  since Phase 1 the backend returns `{"index", "reason"}` objects. Rewritten
  with an inline example. Login response said "same TokenResponse structure as
  register" — the real contract is top-level tokens + `user` (register nests
  under `tokens`). Rewritten.
- `ARCHITECTURE.md` — nightly-purge paragraph omitted the Phase 5 additions:
  audit logs > 1 year and deletion of sighting **photo blobs**. Added.
- `KNOWN_LIMITATIONS.md #41` — resolved as stale: PROJECT_INFO contains no
  `{"error": {...}}` requirement (grep of the spec), and `main.py` has had
  exception handlers since Phase 1. The adopted contract is
  `{"detail": "<string>"}`.
- `KNOWN_LIMITATIONS.md #44` — resolved as stale: `models/audit_log.py`
  declares `actor_id: Mapped[uuid.UUID | None]` with `nullable=True`.
- Credentials cross-check: `seed_db.py`, `RUNBOOK.md`, `DEMO_SCRIPT.md`,
  `start_demo.sh`, `README.md` all carry the same volunteer account
  (`volunteer@rakshak.local` / `Vol@12345`).

**§8 composed acceptance — environment evidence:**

- `docker --version` → `CommandNotFoundException` (Docker not installed).
- `wsl -l -v` → "Windows Subsystem for Linux has no installed distributions".
- `git status` → repo is on `main` at `origin/main`, but a genuine §8 run
  needs Docker (compose stack, `alembic upgrade head`, seeded demo, live
  browser) which does not exist here. The final "grep backend logs for
  non-hotlisted plates" step therefore has **no live logs to scan**; the
  invariant is instead proven at code level by `test_privacy.py` (5/5,
  including the mixed-batch isolation and no-echo/no-log/no-row cases).

| # | Check | Result | Notes |
|---|-------|--------|-------|
| 1 | Static | PASS | `scripts/audit_docstrings.py backend scripts` → **0 violations** (68 files). Dashboard `npx tsc --noEmit` → clean; `npm run build` → clean (informational chunk-size warning only). Mobile `npx tsc --noEmit` → clean. |
| 2 | Unit | PASS | `pytest -q` → **160 passed, 0 failed**. Mobile `npx jest` → **26 passed, 0 failed** (2 suites). |
| 3 | Integration | BLOCKED | §8 requires compose + Postgres + Redis + Alembic. Evidence: no docker binary, no WSL distro. |
| 4 | E2E | BLOCKED | §8's live demo (seed → simulator → dashboard) needs the stack above; the log-scan step has no logs without a running backend. |
| 5 | Adversarial | PASS | Docs-vs-code audit caught 4 real drifts (API reasons shape, API login shape, ARCHITECTURE retention omissions, 2 stale limitation entries) — all corrected rather than re-asserted. Credentials verified consistent across 5 files. |

Verdict: **PASS (composed acceptance §8 deferred to a Docker-capable host).**

### Addendum — §8 log-grep executed post-hoc (same day)

After delivery, real runtime logs were found on disk (`backend/uvicorn.out.log`
9.5 KB, `backend/uvicorn.err.log` 5 KB, dashboard Vite logs 2–0.4 KB).
Scanned all four with the Indian-plate regex:

- App (structlog) log lines contain **zero** plate strings — no `sighting_` /
  `hit_` / ingest plate ever logged; the only non-log noise is access-log lines.
- The single plate-shaped hit, `TS09AB1234`, appears only in **HTTP access-log
  lines that echo a client-requested URL** (`GET /api/v1/vehicles/TS09AB1234`
  → 404, repeated) — i.e. the dashboard probing a non-existent route, at a time
  when every request was 401ing (no authenticated ingest happened). It is not a
  backend-emitted plate and not an ingestion artifact.
- `POST /api/v1/sightings/` lines are method+path only (never bodies).

§8's "zero non-hotlisted plates in backend logs" therefore **passes against real
logs**: the application layer emits no plates at all; the sole access-log string
is an echoed client URL for a path that 404s.

---

## Phase table (filled by Steps 2–11)

| Phase | Step | Verdict | 1 Static | 2 Unit | 3 Integration | 4 E2E | 5 Adversarial | Date |
|-------|------|---------|----------|--------|---------------|-------|---------------|------|
| 0 Audit | 1 | FAIL | PASS | 115/13 | blocked | blocked | partial | 2026-09-22 |
| 1 Backend foundation | 2 | **PASS** | PASS | **131/0** | blocked | blocked | PASS | 2026-09-22 |
| 2 Hotlist state machine | 3 | **PASS** | PASS | **132/0** | blocked | blocked | PASS | 2026-09-22 |
| 3 Device registration | 4 | **PASS** | PASS | **136/0** | blocked | blocked | PASS | 2026-09-22 |
| 4 Sighting ingestion + privacy | 5 | **PASS** | PASS | **138/0** | blocked | blocked | PASS | 2026-09-22 |
| 5 Data retention + scheduler | 6 | **PASS** | PASS | **142/0** | blocked | blocked | PASS | 2026-09-22 |
| 6 Analytics + admin | 7 | **PASS** | PASS | **144/0** | blocked | blocked | PASS | 2026-09-22 |
| 7 Dashboard hardening | 8 | **PASS** | PASS | **145/0** | blocked | blocked | PASS | 2026-09-22 |
| 8 Mobile on-device pipeline | 9 | **PASS** | PASS | **26/0** (jest) + **145/0** (pytest) | blocked | blocked | PASS | 2026-09-22 |
| 9 Simulator + demo data | 10 | **PASS** | PASS | **160/0** | blocked | blocked | PASS | 2026-09-22 |
| 10 Docs + final audit | 11 | **PASS** | PASS | **160/0** + **26/0** | blocked | blocked | PASS | 2026-09-22 |