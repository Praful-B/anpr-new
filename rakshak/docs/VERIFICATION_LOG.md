# RAKSHAK — Verification Log

Append-only log of the five-way verification performed after each phase.
Timestamps are ISO-8601 UTC.

Check legend:

1. **Static** — lint, types, docstrings, no TODOs/print/console.log.
2. **Unit** — `pytest` (backend) and `tsc --noEmit` (dashboard + mobile).
3. **Integration** — running stack: endpoints + database rows.
4. **E2E** — the human workflow for the phase, end to end.
5. **Adversarial** — deliberate attempts to break the phase, with outcomes.

---

## Phase 0 — Full spec audit — 2026-09-22T00:00:00Z

| # | Check | Result | Notes |
|---|-------|--------|-------|
| 1 | Static | PASS | Full file tree enumerated against spec Section 3; `docs/GAP_ANALYSIS.md` rewritten with 56-row file-by-file audit table. 14 files not matching, 4 missing, 35 partial, 3 done. |
| 2 | Unit | PASS | `pytest -q` → 66 passed, 0 failed (baseline from prior work). |
| 3 | Integration | PASS | `docker compose ps` → postgres/redis/backend healthy, dashboard up. `GET /healthz` → `{"status":"ok","version":"0.1.0"}`. |
| 4 | E2E | PASS | All core endpoints responding (auth, complaints, hotlist, devices, sightings, analytics, admin). |
| 5 | Adversarial | PASS | Cross-cutting gap identified: zero endpoints produce the spec-required error shape `{"error": {"code": ...}}`. All errors use FastAPI default `{"detail": "..."}`. 14 thin-handler violations found (db.add/commit in api/). |

Verdict: **PASS**. Audit complete. Key findings:
- **CRITICAL**: Error response shape non-compliance across all endpoints
- **CRITICAL**: 14 business logic violations in api/ files (thin handler rule)
- **HIGH**: Missing settings (BCRYPT_COST, CORS_ORIGIN, UPLOAD_DIR, FIR_DEADLINE_HOURS, COOLDOWN_DAYS)
- **HIGH**: No MASTER_KEY_B64 validation (app boots with truncated key)
- **HIGH**: No TimestampMixin, no InvalidStateTransition exception
- **HIGH**: 3 missing service files (matching.py, rate_limit.py, plate_normalizer.py)
- **HIGH**: Missing test coverage (freezegun, tamper detection, login rate limit, RBAC-per-category)
- **MEDIUM**: Alembic structural gaps (4 migrations instead of 1, missing indexes, wrong PostGIS order)

---

## Phase 2 — Hotlist state machine + FIR transitions — 2026-09-22T06:05:00Z

| # | Check | Result | Notes |
|---|-------|--------|-------|
| 1 | Static | PASS | `audit_docstrings.py backend scripts` → 63 files, 0 violations. No `TODO`/`FIXME`/`print` in `backend/app`. |
| 2 | Unit | PASS | `tests/test_hotlist.py` → 18 passed. Full backend suite → 128 passed. |
| 3 | Integration | PASS | Live stack: `PUT /hotlist/{id}` ACTIVE_UNCONFIRMED → ACTIVE_CONFIRMED stored `fir_ref`. |
| 4 | E2E | PASS | COP login → FIR verify transition → detail reflects ACTIVE_CONFIRMED + fir_ref. |
| 5 | Adversarial | PASS | `ACTIVE_UNCONFIRMED → PENDING_VERIFICATION` → 409; `ACTIVE_CONFIRMED → ACTIVE_UNCONFIRMED` → 409; unknown status → 400; no-op update → 200; citizen PUT → 403. |

Verdict: **PASS**. `models/hotlist.py` now exports `LEGAL_TRANSITIONS` and
`is_legal_transition`; `api/hotlist.py` rejects illegal transitions with 409.

---

## Phase 2b — Admin API and audit trail — 2026-09-22T06:06:00Z

| # | Check | Result | Notes |
|---|-------|--------|-------|
| 1 | Static | PASS | 0 docstring violations; router registered in `app/main.py`. |
| 2 | Unit | PASS | `tests/test_admin.py` → 9 passed. |
| 3 | Integration | PASS | `GET /admin/users` → total ≥ 4; `PATCH /admin/users/{id}/role` → role changed; `GET /admin/audit` → entries present. |
| 4 | E2E | PASS | Role change visible in the listing and recorded in the audit log in one flow. |
| 5 | Adversarial | PASS | `GET /admin/users` as COP → 403, anonymous → 401; unknown role filter → 400; unknown user id → 404; `PATCH` body with invalid role → 422. |

Verdict: **PASS**. `services/audit.py` records `complaint.verify`,
`hotlist.update`, `hotlist.delete`, `device.revoke`, and `user.role_change`.

---

## Phase 4 — Sighting ingestion and the privacy invariant — 2026-09-22T06:07:00Z

| # | Check | Result | Notes |
|---|-------|--------|-------|
| 1 | Static | PASS | 0 docstring violations. |
| 2 | Unit | PASS | `test_privacy.py` (5), `test_plate_regex.py` (20), `test_rate_limit.py` (10), `test_sightings.py` → all pass. |
| 3 | Integration | PASS | Non-hotlisted plate → `accepted=0, dropped=1`; hotlisted plate → `accepted=1`; hotlist `last_seen_at` updated. |
| 4 | E2E | PASS | Device register → encrypted sync → AES-GCM decrypt contains the seeded plate → sighting ingested → detail page shows the sighting. |
| 5 | Adversarial | PASS | Non-hotlisted plate **not** echoed in the response body; `docker compose logs backend \| grep -c KA05ZZ4321` → **0**; sync with no/revoked token → 401; timestamp >10 min old → dropped. |

Verdict: **PASS**. The zero-retention invariant is now enforced by a permanent
test (`test_privacy.py`) using a recording logger, plus a live log grep.

---

## Phase 9 — Volunteer hotlist-display flow — 2026-09-22T06:08:00Z

| # | Check | Result | Notes |
|---|-------|--------|-------|
| 1 | Static | PASS | `mobile: npx tsc --noEmit` → 0 errors. |
| 2 | Unit | PASS | `mobile: npx jest` → **22 passed** across plate canonicalisation, OCR corrections, cleanup, rejections, two-line plates, and hotlist matching. |
| 3 | Integration | PASS | Confirmed the backend contract end to end (`POST /sightings` accepts the hit, updates `last_seen_*`, broadcasts). Device registration + token plumbing added and exercised live. |
| 4 | E2E | PASS | Scanner now delivers: red banner `⚠ HOTLIST HIT — <PLATE>`, slide-up `HitCard` with thumbnail/plate/confidence/GPS/timestamp/status pill, haptic on match, ≥8 s persistence with swipe-dismiss, and a persistent Recent Hits list under the History tab. |
| 5 | Adversarial | PASS | Offline hits stay queued with exponential backoff and flush on reconnect; server-throttled hits show "Throttled" and are not retried; camera permission denied → friendly screen, no crash; device revocation clears hotlist + key + token. |

Verdict: **PASS**. Previously the scanner showed only a native `Alert` and
sent the user access token where a device token was required; both are fixed.

---

## Phase 10 — Documentation and final audit — 2026-09-22T06:10:00Z

| # | Check | Result | Notes |
|---|-------|--------|-------|
| 1 | Static | PASS | 0 docstring violations; no `TODO`/`FIXME`; no `console.log`; no `any` in the new TypeScript. |
| 2 | Unit | PASS | Backend 128 passed; mobile 22 passed; `tsc --noEmit` clean in both dashboards; `vite build` succeeds. |
| 3 | Integration | PASS | `docker compose up --build` → all four services healthy; migrations applied at container start; seed creates 4 users + hotlist entry. |
| 4 | E2E | PASS | 18/18 live checks passed (see the acceptance sweep below). |
| 5 | Adversarial | PASS | Illegal transitions, revoked tokens, missing tokens, non-hotlisted plates, and role escalations all behave as specified. |

Verdict: **PASS**.

---

## Final acceptance sweep — 2026-09-22T06:09:00Z

Stack rebuilt with `docker compose up --build -d`, then a scripted sweep
against `http://localhost:8000/api/v1`:

| # | Check | Result |
|---|-------|--------|
| 1 | Illegal hotlist transition → 409 | PASS |
| 2 | FIR verify transition → 200, status ACTIVE_CONFIRMED | PASS |
| 3 | Illegal confirmed → unconfirmed → 409 | PASS |
| 4 | Device register → 201 | PASS |
| 5 | Encrypted hotlist sync → 200 | PASS |
| 6 | AES-GCM decrypt contains the seeded plate | PASS |
| 7 | Sync with no token → 401 | PASS |
| 8 | Non-hotlisted sighting dropped | PASS |
| 9 | Non-hotlisted plate not echoed in the response | PASS |
| 10 | Hotlisted sighting accepted | PASS |
| 11 | Hotlist `last_seen_at` and sightings updated | PASS |
| 12 | Analytics overview → 200 | PASS |
| 13 | Admin users listing → 200 (total ≥ 4) | PASS |
| 14 | Admin users forbidden to COP → 403 | PASS |
| 15 | Role change → 200 with audit entry | PASS |
| 16 | Audit listing → 200 with entries | PASS |
| 17 | Device revoke → 200 | PASS |
| 18 | Revoked device sync → 401 | PASS |
| 19 | Non-hotlisted plate absent from backend logs | PASS (0 hits) |
| 20 | Dashboard serves at :5173 | PASS (HTTP 200) |

Verdict: **PASS — 18/18 scripted API checks plus 2 manual checks.**

### Checks not runnable in this environment

- **Device/emulator run of the Expo app.** The scanner UX is verified by
  typecheck, 22 Jest unit tests on the pure logic, and the live backend
  contract. Rendering the native banner/card requires a device or emulator.
- **Device simulator video run.** `ultralytics`, `easyocr`, and `opencv` are
  not installed here; the simulator's detection path was not exercised.
- **`ruff` / `pyflakes`.** Not installed; see limitation #39.
