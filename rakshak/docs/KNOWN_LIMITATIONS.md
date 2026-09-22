# Known Limitations

This document lists every deferral, prototype shortcut, and assumption made during the RAKSHAK build. Nothing is hidden.

> **Scope of this revision (Step 12 — final verification & polish):** the
> entries marked *(added in Step 12)* were recorded while closing out the
> build. They cover the honest limits of the photo UI, the template-driven
> configuration files, and the metrics used by `scripts/audit_docstrings.py`.

---

## Prototype shortcuts (privacy-critical)

### 1. On-device TFLite inference not implemented

The mobile app (`src/ai/inference.ts`) attempts to load `react-native-fast-tflite` with a YOLO11n TFLite model but always falls back to the backend `POST /api/v1/detect` endpoint. This **violates the zero-retention privacy promise** (§2 of PROJECT_INFO.md) because raw camera frames are transmitted to the server.

**Production fix required:**
1. Eject from Expo managed workflow or use a custom dev client.
2. Install `react-native-fast-tflite` with native TFLite runtime.
3. Convert YOLO11n and OCR models to TFLite format.
4. Remove the `/detect` backend endpoint.

### 2. Backend `/detect` endpoint exists

The `POST /api/v1/detect` endpoint (in `backend/app/api/detect.py`) accepts base64-encoded camera frames and runs YOLO+OCR server-side. This exists **only as a prototype fallback** and should be removed before any production deployment.

---

## Security and auth deferrals

### 3. Access token stored in expo-secure-store

Per §9 of PROJECT_INFO.md, access tokens should be held in memory only. The mobile app currently stores them in both in-memory state and expo-secure-store for session restore on app restart. Production builds should use biometric-protected secure store or Keychain with short TTL.

### 4. Mobile navigation uses useState router

The mobile app uses a simple `useState`-based screen router instead of `@react-navigation/native-stack`. Lacks deep linking, back button handling, and transition animations. A production build should integrate React Navigation properly.

### 5. Hotlist sync silent failure

The hotlist sync silently fails if the device key is missing or the server returns an error. Production UI should surface sync status and prompt re-authentication if the device key is lost (e.g., after app reinstall).

---

## Database and data model assumptions

### 6. Email validation uses regex (not email-validator)

The `email-validator` library rejects `.local` TLD addresses used in the seed script (`admin@rakshak.local`, etc.). A regex-based validator is used instead. Production deployments should switch to `email-validator` with real domains.

### 7. Alembic migration ownership from Docker

Migration files are generated inside the Docker container and owned by `root`. Host-side writes fail without elevated privileges. Cosmetic issue that does not affect functionality.

### 8. AuditLog uses JSON (not JSONB)

The `AuditLog.metadata_json` column uses `JSON` instead of `JSONB` for SQLite test compatibility. PostgreSQL production deployments should migrate this column to `JSONB` for GIN indexing support.

### 9. Analytics bucketing happens in Python *(revised in Step 12)*

The analytics endpoints originally used SQLite-only SQL (`strftime`, `julianday`), which raised `UndefinedFunction` on PostgreSQL and broke four of the six endpoints in the docker-compose stack. They now fetch the matched timestamp/coordinate rows and bucket weeks, hours, and weekdays in Python, so identical queries run on SQLite and PostgreSQL. The trade-off is that a very large `sightings` table would transfer more rows than a SQL-side `GROUP BY`; at that scale, move the bucketing back into SQL with `date_trunc`/`EXTRACT` or maintain a materialised aggregate. See `backend/app/api/analytics.py` for the exact semantics (`week_start` is the ISO date of the Monday; `by_day` starts at Sunday).

### 10. Plate normaliser positional correction is heuristic

The plate normaliser applies OCR error corrections (O→0, I→1, B→8, S→5, Z→2 in digit positions; 0→O, 1→I in alpha positions) using a heuristic that infers the Indian plate structure by scanning for alpha/digit transitions. Works for well-formed plates but may mis-correct heavily garbled OCR output. Full positional correction based on known RTO codes is deferred.

---

## Infrastructure and scaling

### 33. Trailing-slash paths redirect *(added in Step 12)*

FastAPI registers the collection routes as `/api/v1/sightings/` and `/api/v1/hotlist/` (with a trailing slash). Requests to the slash-less form receive a `307` redirect that preserves the method and body. The dashboard and the device simulator now call the canonical paths with the trailing slash, but any external client that omits it will see one extra round trip.

### 34. passlib logs a trapped bcrypt warning *(added in Step 12)*

`make seed` prints `(trapped) error reading bcrypt version` from passlib 1.7.4, which reads the removed `bcrypt.__about__` attribute. passlib recovers and hashing works correctly; the output is cosmetic noise from a known passlib/bcrypt 4.x incompatibility.

### 11. WebSocket broadcast is in-memory only

The `ConnectionManager` stores WebSocket connections in a Python list. In a multi-worker deployment (e.g., uvicorn with `--workers`), broadcasts are limited to connections on the same worker process. A Redis Pub/Sub layer is needed for horizontal scaling.

### 12. Object store is local filesystem only

The `StorageBackend` abstraction supports `local` and `s3` backends, but only `LocalFileSystemBackend` is implemented. S3/MinIO integration is deferred. Photos are stored in `./data/uploads/` which is ephemeral in Docker.

### 13. No HTTPS / TLS termination

The docker-compose stack exposes HTTP only. Production deployments require a reverse proxy (nginx, Caddy, or cloud load balancer) for TLS termination.

### 14. No rate limiting on login in seed environment

The Redis-based rate limiter for `POST /auth/login` (10 per IP per 15 minutes) is configured but may not trigger in the seed/demo environment if Redis is not fully warmed up.

---

## Device simulator limitations

### 15. YOLO model must be downloaded separately

The device simulator loads `yolo11n.pt` from the current working directory. This file must be downloaded separately (ultralytics auto-downloads on first run, or place manually). The model is used as a stand-in for the actual on-device TFLite model.

### 16. Sample videos are not Indian traffic

The download script uses public sample clips from OpenCV and Intel IoT repositories. These are short clips not specifically of Indian traffic. For a realistic demo, replace `data/samples/` with actual Indian footage containing visible licence plates. Two further caveats *(added in Step 12)*: the script tolerates an unreachable network by warning and continuing, so `data/samples/` may legitimately end up empty; and `sample1.mp4` is actually an AVI payload served under an `.mp4` name, which OpenCV sniffs by content rather than extension.

### 17. EasyOCR runs CPU-only

The device simulator runs EasyOCR in CPU mode (`gpu=False`). GPU acceleration requires `torch` with CUDA support, which significantly increases Docker image size.

### 18. Offline queue uses hardcoded SQLite path

The offline queue uses a hardcoded path `device_simulator_queue.db` in the current working directory. Acceptable for single-device demo use. Multi-device deployments should use per-device database paths.

### 32. Simulator dependencies live outside the compose stack *(added in Step 12)*

`scripts/device_simulator.py` needs OpenCV, numpy, requests, ultralytics, and EasyOCR on the host. They are pinned in `scripts/requirements-simulator.txt` and are deliberately absent from `backend/requirements.txt`, so the backend image stays small. `make demo` checks for them and prints the install command when they are missing.

### 19. Temporal voting uses placeholder tracker IDs

The simulator uses a monotonically incrementing integer as the tracker ID (placeholder for actual YOLO track IDs). Real YOLO11 tracking provides stable per-object IDs across frames, which gives more accurate temporal voting. The current approach may over-count matches when multiple plate detections occur in the same frame.

---

## Seed and demo data

### 20. Seed script requires backend dependencies locally

The seed script at `scripts/seed_db.py` resolves its `sys.path` relative to the backend directory. When run from the host, it requires Python dependencies installed locally. When run inside the container, the `scripts/` directory must be mounted or the file copied in.

### 21. Demo accounts use weak passwords

The seed script creates accounts with passwords like `Admin@123`, `Cop@12345`. These are intentionally simple for demo purposes. Production deployments must enforce strong password policies.

### 31. Development master key is committed *(added in Step 12)*

`.env.example` ships a fixed 32-byte `MASTER_KEY_B64` so `cp .env.example .env && make up && make seed` works end to end without extra steps. It is a development-only key that anyone with the repository can read. Replace it (and `JWT_SECRET`) before any real deployment: a leaked master key allows deriving every device's hotlist key.

---

## Frontend (dashboard)

### 28. Sighting photos are stored but never rendered *(added in Step 12)*

The backend stores each hit photo through `StorageBackend` and serves it from the local mount at `/sightings/<file>` (proxied by nginx and the Vite dev server). No dashboard component renders that image yet: the vehicle detail page shows location, timestamp, and confidence, but not the photo thumbnail. The API field `photo_url` is therefore present and resolvable but unused by the UI.

### 29. Relative API base requires the proxy *(added in Step 12)*

The dashboard ships with `VITE_API_URL=/api/v1`, so requests are relative and must be proxied to the backend. nginx handles `/api/`, `/sightings/`, and `/ws/` in the production image, and `vite.config.ts` proxies the same prefixes in dev using `VITE_PROXY_TARGET` (default `http://backend:8000`). Running `npm run dev` outside docker-compose requires setting `VITE_PROXY_TARGET` to a reachable backend.

### 22. No offline support

The dashboard has no service worker or offline caching. Loss of network connectivity renders it unusable.

### 23. No internationalisation (i18n)

All UI text is in English. Hindi and regional language support is deferred.

### 24. Admin page is implemented but unpaginated in the UI *(revised)*

The `/admin` route now renders `AdminPanel.tsx`, which lists users with a role filter, changes a user's role, and shows the audit log. The UI fetches only the first page (20 rows) of each list and has no next/previous controls; the API itself is fully paginated. Deep paging is deferred.

---

## Mobile app

### 25. No push notifications

The mobile app does not use push notifications for hotlist updates or sighting alerts. Relies on periodic background sync (every 15 minutes).

### 26. Camera permission flow is handled *(revised)*

The scanner now requests camera permission with `useCameraPermissions` and renders an explicit "Camera permission is required for plate scanning" screen with a re-request button when denied, instead of crashing. Location permission denial is likewise surfaced in the status line, and hits are recorded with null coordinates in that case.

### 27. No background camera scanning

The scanner only runs when the app is in the foreground. Background scanning would require native module integration and is deferred.

### 30. EXPO_PUBLIC_API_URL must be set *(added in Step 12)*

The mobile API client reads its base URL from `EXPO_PUBLIC_API_URL` and throws a descriptive error at import when it is missing, instead of falling back to a hardcoded host. Copy `mobile/.env.example` to `mobile/.env` and point it at a backend reachable from the device (LAN address, `10.0.2.2` for the Android emulator, or a tunnel).

---

## Volunteer hit UX and mobile module layout *(added in this revision)*

### 35. Scanner quality filter is not implemented on mobile

Flow C step 2 (Laplacian-variance blur rejection and mean-brightness darkness rejection) is implemented in `scripts/device_simulator.py` but **not** in `mobile/src/screens/Scanner.tsx`, because reading pixels from an Expo photo needs an extra native path. The scanner relies on the temporal-voting threshold and OCR confidence instead. Production should add the blur/brightness gate.

### 36. Recent Hits thumbnails reference the local cache file

`src/services/hitHistory.ts` stores the `expo-image-manipulator` output URI as the hit thumbnail. That file lives in the app cache directory and can be evicted by the OS, in which case the Recent Hits list shows the card without a thumbnail. Copying the frame into the app document directory would make it durable.

### 37. Mobile module layout differs slightly from §7

Three modules were added or split beyond the §7 list because the app could not otherwise complete a hit end-to-end: `src/services/device.ts` (device registration, previously absent — the scanner was sending the *user* access token as the `X-Device-Token` header), `src/components/HitCard.tsx` (the slide-up hit card), and `src/services/hitHistory.ts` (the persistent Recent Hits store). `src/services/crypto.ts` and `src/ai/match.ts` were extracted from `hotlist.ts` and `inference.ts` respectively to match §7 and to make the logic unit-testable.

### 38. Backend service-module names differ slightly from §7

`services/matching.py` and `services/rate_limit.py` from §7 do not exist as separate files: hotlist matching lives in `api/sightings.py` (`_find_active_hotlist`) and the complaint rate limiter lives in `api/complaints.py` (`_check_rate_limit`). A new `services/audit.py` was added for audit-log writes, and `ConnectionManager` lives in `api/ws.py` rather than a standalone `ws_manager.py`. Behaviour matches the spec; only the file boundaries differ.

### 39. Ruff and pyflakes are unavailable in the build sandbox

`ruff` and `pyflakes` are not installed in this environment and were not added. The static check for this pass used `scripts/audit_docstrings.py` (0 violations across 63 files, including a 40-line function cap), a grep for `TODO`/`FIXME`/`print`, and `pytest` (which imports every module, so syntax and import errors surface). Run `ruff check backend/` in a full development environment before release.

### 40. Hit delivery status is per-batch, not per-event

The backend accepts a batch and returns aggregate `{accepted, dropped, reasons}`. The mobile app sends one event per request so the reported status is unambiguous, but a future batched sender would have to reconcile per-event outcomes from the `reasons` list.

---

## Spec audit gaps (Phase 0 — added in this revision)

### 41. Error response shape is non-compliant

All endpoints return FastAPI's default `{"detail": "..."}` error format. The spec requires `{"error": {"code": "SOME_MACHINE_CODE", "message": "...", "field": null}}`. No custom exception handler exists in `main.py`. This is a cross-cutting fix that affects every error path.

### 42. Thin handler rule violated across 6 API files

The spec requires route handlers to be thin (validate, call service, return). 14 occurrences of `db.add()` / `db.commit()` were found inside `api/` files: `auth.py`, `complaints.py`, `devices.py`, `hotlist.py`, `admin.py`, `sightings.py`. Business logic must be extracted to `services/` functions.

### 43. MASTER_KEY_B64 has no startup validation

`config.py` accepts any string for `MASTER_KEY_B64` including empty strings. The spec requires a validator that base64-decodes and checks `len == 32`, failing fast at startup. Currently the app boots fine with a truncated key and would fail at first crypto operation.

### 44. AuditLog.actor_id is NOT NULL (should be nullable)

The `audit_logs` table has `actor_id` as NOT NULL FK to users. The spec requires it to be nullable for system actions (e.g., FIR expiry scheduler writes audit log with `actor_id=NULL`). This blocks the scheduler's audit logging requirement.

### 45. No InvalidStateTransition custom exception

`services/verification.py` raises `ValueError` for illegal state transitions. The spec requires a typed `InvalidStateTransition` exception. No such class exists anywhere in the codebase.

### 46. Refresh token includes role claim

`security.py` includes `role` in refresh token payloads. The spec says refresh tokens should contain only `{sub, exp, iat, type:"refresh"}` — no role. This is a minor security concern (role could become stale if user role changes between token issuance and refresh).

### 47. decode_token does not enforce type checking

`decode_token()` returns raw decoded payload without checking the `type` claim. The caller in `deps.py` checks `type == "access"`. The spec says `decode_token` should accept an `expected_type` parameter and enforce it. Currently an access token could be used where a refresh token is expected if the caller forgets to check.

## Assumptions

1. **Indian licence plate format:** The system assumes plates follow the format `^[A-Z]{2}[0-9]{1,2}[A-Z]{1,3}[0-9]{4}$`. International plate formats are not supported.
2. **Single-country deployment:** All coordinates are in India. The hotlist sync and sighting ingestion do not handle cross-border scenarios.
3. **Single-tenant:** One police department per deployment. No multi-tenancy.
4. **Government fleet vehicles:** Assumes fleet vehicles have persistent internet connectivity for hotlist sync. Volunteer devices may have intermittent connectivity.
5. **Photo evidence:** The system stores sighting photos but does not perform secondary verification or tamper detection on uploaded proof documents.
6. **FIR verification is manual:** Officers manually verify FIR references. No integration with police records systems.
7. **Complaint `notes` are accepted but not persisted *(added in Step 12)*:** `POST /complaints` accepts an optional multipart `notes` field so the dashboard form and API contract stay stable, but the `complaints` table (§5) has no notes column, so the value is discarded. Persisting it requires a schema change plus a migration.
8. **Function-length budget is measured in code lines *(added in Step 12)*:** §12.8 of PROJECT_INFO.md caps functions at 40 lines. `scripts/audit_docstrings.py` counts the definition and its statements while excluding the docstring block, blank lines, and comment-only lines, because §12.2 simultaneously requires a purpose/Args/Returns/Raises docstring on every function. The report also prints the full source span so the raw footprint stays visible.
9. **Migrations run at container start *(added in Step 12)*:** the backend service command is `alembic upgrade head && uvicorn ...`, so a clean `make up` always produces a migrated database. Running Alembic manually (`make migrate`, `alembic revision --autogenerate`) inside the container still works and remains the way to add new revisions.
10. **Schema is owned by Alembic *(added in Step 12)*:** to close the §12.14 gap found during this pass, a migration was added for the `sightings` and `audit_logs` tables and the PostGIS extension. `scripts/seed_db.py` still calls `Base.metadata.create_all` as an idempotent safety net for SQLite-only or partially migrated databases.
