# RAKSHAK — PROJECT INFORMATION (READ FIRST, DO NOT EDIT)

You are building RAKSHAK. Every prompt you receive assumes you have read this file. If a prompt conflicts with this file, ask before proceeding. If this file does not answer something, prefer the simplest reasonable option and note it in docs/KNOWN_LIMITATIONS.md.

## 1. What RAKSHAK is
A privacy-first mobile ANPR network for stolen vehicle detection. Citizens file complaints. After ownership verification, the plate goes on a hotlist. Phones on government fleet vehicles and volunteer citizens run on-device AI that scans plates. When a scanned plate matches the hotlist, its location + photo + timestamp reach a police dashboard in near real time. Non-matching plates are never stored, never transmitted.

## 2. Core privacy promise (never violate)
The backend NEVER receives non-matching plates. Ever. This is the product's entire pitch. Any code path that would transmit an unmatched plate is a bug.

## 3. Architecture — FINAL, do not redesign

### 3.1 Matching model
- BOTH fleet and volunteer devices perform on-device matching.
- Hotlist is downloaded encrypted with per-device AES-256-GCM key.
- Per-device key = HKDF(master_key, info=device_id, salt=version). Master key from env `MASTER_KEY_B64` (32 bytes).
- Key stored in OS keystore via expo-secure-store.
- Hotlist decrypted in memory only during matching. Never written to disk plaintext. Never shown in the UI.
- HONEST SECURITY CLAIM: "encrypted at rest, decrypted in memory, not exposed in UI, remotely wipeable." Do NOT claim "app cannot read hotlist."

### 3.2 Detection transport
- Devices send ONLY hit events (matched plates).
- Unmatched detections discarded within one frame loop, on-device.
- Offline: hits queued in local SQLite, flushed on reconnect.

### 3.3 Photo storage
- Object store abstraction (`StorageBackend` interface: put/get/delete).
- Prototype: local filesystem. Prod: S3/MinIO. Same interface.
- DB stores only the URL, never the blob.

### 3.4 Real-time dashboard
- WebSocket at `/ws/dashboard?token=<jwt>`, COP role only.

### 3.5 FIR verification
- Officer manually enters FIR reference in dashboard, clicks Verify. Flips hotlist entry to ACTIVE_CONFIRMED.

### 3.6 Throttling & dedup
- Server: max 1 accepted hit per (device_id, plate) per 30 seconds.
- Same plate across devices within 90 seconds → merged into one "sighting cluster" (shared cluster_id in DB). Raw hits still stored.

## 4. Tech stack — FINAL, do not substitute
- Backend: Python 3.11 + FastAPI + SQLAlchemy 2.x + Alembic
- DB: PostgreSQL 15 + PostGIS
- Queue/cache: Redis 7
- Auth: python-jose[cryptography], passlib[bcrypt]
- Crypto: `cryptography` lib (AES-256-GCM, HKDF)
- Scheduler: APScheduler (in-process, NOT Celery)
- Server: uvicorn
- Config: pydantic-settings reading .env
- CV: ultralytics YOLO11n (pretrained yolo11n.pt as stand-in)
- OCR: easyocr (fallback paddleocr)
- Mobile: React Native + Expo (managed), expo-camera, expo-secure-store, expo-sqlite, expo-location
- Mobile inference: react-native-fast-tflite for prototype; if integration > 2h, fall back to "send frame to /detect" and document the shortcut
- Dashboard: React 18 + TypeScript + Vite + TailwindCSS + Leaflet + leaflet.heat + Recharts + react-router-dom + native WebSocket
- Infra: Docker + Docker Compose (Postgres, Redis, backend, dashboard, device simulator)

## 5. Data models (SQLAlchemy, UUID PKs, created_at/updated_at everywhere)

- users: id, name, email(unique), phone, password_hash, role ENUM(CITIZEN,VOLUNTEER,COP,ADMIN)
- devices: id, user_id FK, type ENUM(FLEET,VOLUNTEER), token_hash, encryption_key_wrapped, revoked bool, last_sync_at
- complaints: id, user_id FK, plate(varchar20, indexed, uppercase, no spaces), proof_ref, status ENUM(PENDING_VERIFICATION,VERIFIED,REJECTED), rejection_reason
- hotlist: id, plate(indexed), complaint_id FK, status ENUM(PENDING_VERIFICATION,ACTIVE_UNCONFIRMED,ACTIVE_CONFIRMED,EXPIRED,CLOSED,REJECTED), added_at, fir_deadline, fir_ref, fir_verified_at, cooldown_until, recovered_at, last_seen_at, last_seen_lat, last_seen_lng, dismissed bool
- sightings: id, hotlist_id FK(indexed), device_id FK, lat, lng, captured_at(tz-aware), photo_url, confidence, cluster_id (nullable)
- audit_logs: id, actor_id FK, action, target_type, target_id, metadata JSONB

Indexes: sightings(hotlist_id, captured_at), sightings(device_id, captured_at), hotlist(plate), hotlist(status), complaints(user_id, created_at)

## 6. API surface — all under /api/v1, JWT in Authorization: Bearer

Auth:
- POST /auth/register (name, email, phone, password, role)
- POST /auth/login
- POST /auth/refresh

Complaints:
- POST /complaints (rate limited: 3/user/24h, 10/IP/24h → 429 with Retry-After)
- GET /complaints/mine
- POST /complaints/{id}/fir

Verification (COP/ADMIN):
- POST /complaints/{id}/verify {decision: approve|reject, reason?}

Devices:
- POST /devices/register → returns {device_id, device_token(once), encryption_key_b64}
- GET /hotlist/sync → {version, iv, ciphertext, key_id}
- POST /devices/{id}/revoke (ADMIN)

Sightings:
- POST /sightings (device auth via X-Device-Token header) {events: [{plate, lat, lng, captured_at, confidence, photo_b64}]} → {accepted, dropped, reasons}
- GET /sightings?plate=&from=&to= (COP)

Hotlist:
- GET /hotlist (COP, filters status/plate/date, paginated)
- GET /hotlist/{id} (COP, includes last 50 sightings + complaint)
- PUT /hotlist/{id} (COP, updates status/fir_ref/notes/dismissed)
- DELETE /hotlist/{id} (COP, soft delete → CLOSED)

Analytics (COP, all accept from/to, default last 30 days):
- GET /analytics/overview → total_active_hotlist, total_sightings_last_24h, total_sightings_last_7d, total_recoveries_last_30d, avg_time_to_first_sighting_hours, avg_time_to_recovery_hours
- GET /analytics/heatmap → [{lat, lng, weight}] rounded to 3 decimals (~100m grid)
- GET /analytics/recovery-metrics → per-week time series {week_start, hotlist_added, recovered, expired, recovery_rate}
- GET /analytics/false-positive-rate → {total_hits, hits_dismissed_by_officer, fp_rate, per_device breakdown}
- GET /analytics/device-coverage → per-device stats + aggregate (total, active last 24h, revoked) + map list
- GET /analytics/time-patterns → {by_hour: [24], by_day: [7]}

Admin:
- GET /admin/users, PATCH /admin/users/{id}/role
- GET /admin/audit

WebSocket:
- /ws/dashboard?token=<jwt> (COP) — events: {type: new_sighting|hotlist_change, data: {...}}

## 7. Core flows

### Flow A: Complaint → Hotlist
Citizen registers → POST /complaints → PENDING_VERIFICATION → COP reviews proof → approve → hotlist entry ACTIVE_UNCONFIRMED with fir_deadline = now+48h + WS push. Reject → REJECTED + notify with reason. Scheduler every 5 min expires ACTIVE_UNCONFIRMED past deadline → EXPIRED, cooldown_until = now+7d.

### Flow B: Hotlist sync to device
Device auth → GET /hotlist/sync → {version, iv, ciphertext, key_id} → device decrypts in memory → loads plates into hashset → never persists plaintext.

### Flow C: On-device scanning (every 1s)
1. Grab frame
2. Quality filter: reject if Laplacian variance < threshold (blur) or mean brightness < 40 (dark)
3. YOLO11n plate detection
4. Crop plate
5. OCR → raw text
6. Indian plate regex normalization (see §8)
7. Temporal voting: last N=5 reads for same tracker ID, accept when 3+ agree
8. Match against in-memory hotlist set
9. On match: compress JPEG (~70 quality, max 1280px), build event {plate, lat, lng, captured_at, confidence, photo_b64}, enqueue locally, flush every 5s
10. On no match: DISCARD. No storage. No transmission.

### Flow D: Server hit ingestion
Device auth via X-Device-Token → for each event: validate payload → normalize plate server-side → reverify against active hotlist in DB → throttle (30s same device+plate) → dedup (90s same hotlist_id → same cluster_id) → StorageBackend.put(photo) → insert sighting → update hotlist last_seen_* → WS push new_sighting to COPs → return {accepted, dropped, reasons}.

### Flow E: FIR verification
Citizen POSTs fir_ref → COP verifies → PUT /hotlist/{id} with {status: ACTIVE_CONFIRMED, fir_ref, fir_verified_at} → scheduler no longer expires.

### Flow F: Expiry & cooldown
Scheduler 5 min: ACTIVE_UNCONFIRMED past fir_deadline → EXPIRED, cooldown_until = now+7d. EXPIRED/CLOSED past cooldown_until → purge photos + delete sightings older than 90d.

### Flow G: Recovery
COP sets status CLOSED via PUT /hotlist/{id} with {status: CLOSED, recovered_at: now} → WS hotlist_change → devices drop on next sync.

### Flow H: Device revocation
Admin POST /devices/{id}/revoke → device marked revoked → next sync returns 401 → client wipes hotlist cache + local queue.

## 8. Indian plate regex normalization (CRITICAL — write carefully)
1. Uppercase, strip spaces/hyphens.
2. Positional character correction — walk the string:
   - In digit-expected positions: O→0, I→1, B→8, S→5, Z→2
   - In alpha-expected positions: 0→O, 1→I
   - Expected type derived from state-code + RTO structure.
3. Pattern after correction: ^[A-Z]{2}[0-9]{1,2}[A-Z]{1,3}[0-9]{4}$
4. Two-line plates: if OCR returns a single tall crop, try concatenating halves.

## 9. Security
- JWT: access 15min, refresh 7d. Refresh in HttpOnly cookie (dashboard), access in memory (NOT localStorage).
- Passwords: bcrypt cost 12.
- Device token: 32-byte URL-safe, shown once, stored bcrypt-hashed.
- Rate limits (Redis counters):
  - POST /complaints: 3/user/24h, 10/IP/24h
  - POST /sightings: 1/(device,plate)/30s
  - POST /auth/login: 10/IP/15min
- Every COP/ADMIN write → audit_logs row.
- RBAC server-side always. Client-side guards are cosmetic.

## 10. Data retention
Nightly job: sightings > 90d purge, rejected complaints > 30d purge, expired hotlist entries > 180d after cooldown purge, audit logs retained 1 year.

## 11. Known fixes from original design (do not reintroduce)
- Dual matching conflict → resolved to on-device (§3.1)
- Photo as bytes in DB → object storage (§3.3)
- No dedup rule → §3.6
- No complaint rate limit → §9
- No retention policy → §10
- No device revocation → Flow H
- No officer notification → WS toast
- "App cannot read hotlist" false claim → honest claim in §3.1
- No analytics → §6
- No admin surface → §6

## 12. Code quality rules — NON-NEGOTIABLE
1. Every Python file starts with module docstring (1-3 lines: what it does).
2. Every function and class has docstring: purpose, Args, Returns, Raises.
3. Every TypeScript file starts with JSDoc block.
4. Full type hints (mypy-clean Python, strict:true TS).
5. No magic numbers — named constants at top of file.
6. No commented-out code. Delete unused.
7. No TODOs/FIXMEs in delivered code. Deferred items go in docs/KNOWN_LIMITATIONS.md.
8. Functions < 40 lines. Split if longer.
9. Meaningful names: `hotlist_entry` not `h`, `captured_at` not `t`.
10. Config via env only. `.env.example` documents every variable.
11. Structured logging (structlog or JSON-formatted logging). No print().
12. Explicit error handling. Specific exceptions. Proper HTTP codes. Never swallow silently.
13. DB sessions via FastAPI dependency injection — no global sessions.
14. Alembic initial migration creates all tables + PostGIS extension.
15. Tests: pytest + httpx.AsyncClient. Mock external services.
16. Docker Compose brings up Postgres+PostGIS, Redis, backend, dashboard. Device simulator runs separately.

## 13. Repo structure — EXACT

rakshak/
├── backend/
│ ├── app/
│ │ ├── main.py, config.py, db.py, deps.py, security.py
│ │ ├── models/ (user.py, device.py, complaint.py, hotlist.py, sighting.py, audit_log.py)
│ │ ├── schemas/
│ │ ├── api/ (auth.py, complaints.py, hotlist.py, devices.py, sightings.py, analytics.py, admin.py, ws.py)
│ │ └── services/ (verification.py, matching.py, dedup.py, crypto.py, storage.py, notifier.py, scheduler.py)
│ ├── alembic/
│ ├── tests/ (test_matching.py, test_dedup.py, test_crypto.py, test_fir_expiry.py, test_analytics.py)
│ ├── requirements.txt
│ └── Dockerfile
├── mobile/ (App.tsx, src/screens/, src/services/, src/ai/, src/store/)
├── dashboard/ (src/pages/, src/components/, src/lib/)
├── scripts/ (device_simulator.py, seed_db.py, download_sample_videos.sh)
├── data/samples/
├── docs/ (ARCHITECTURE.md, API.md, RUNBOOK.md, DEMO_SCRIPT.md, KNOWN_LIMITATIONS.md, PROJECT_INFO.md)
├── docker-compose.yml
├── .env.example
└── README.md


## 14. Build order (12 steps)
1. Skeleton + docker-compose + FastAPI /healthz + Alembic init
2. Auth + RBAC + seed script
3. Complaints + hotlist CRUD + FIR expiry scheduler
4. Device registration + HKDF + AES-GCM sync
5. Sightings ingestion + throttle + dedup + storage + WS + all 6 analytics endpoints
6. Device simulator script + sample videos
7. Dashboard: auth + citizen pages
8. Dashboard: police pages (hotlist table, vehicle detail, map, FIR verify)
9. Dashboard: analytics page
10. Mobile app shell + scanner + TFLite (fallback documented)
11. Docs (README, RUNBOOK, DEMO_SCRIPT, ARCHITECTURE)
12. Final pass: pytest green, fresh docker-compose up works, no TODOs, all docstrings present

## 15. Things you must NOT do
- Invent endpoints/models not in §5/§6.
- Use Celery, Kafka, Kubernetes. APScheduler + Redis only.
- Use MongoDB. PostgreSQL + PostGIS only.
- Use Mapbox. Leaflet only.
- Store photos in DB. StorageBackend only.
- Claim "app cannot read hotlist."
- Send unmatched plates to backend. Ever.
- Write "future work" inside code files — put in docs/KNOWN_LIMITATIONS.md.
- Use print(). Use logger.
- Use `any` in TypeScript.
- Skip tests.

## 16. Acceptance criteria (final build)
A fresh dev can: clone → cp .env.example .env → docker-compose up → seed → open localhost:5173 → log in as cop → see seeded hotlist → run device_simulator.py --video sample.mp4 --plate "MH12AB1234" → see hit on dashboard within 5s → open analytics page → see heatmap. Read any file in under 5 minutes.

---

## 17. Changelog

### 2026-09-22 — Step 11: Documentation

- Created `rakshak/README.md` — 5-minute quickstart with clone→configure→up→seed→dashboard→simulator→hit flow. Screenshot placeholders marked for later replacement.
- Created `rakshak/docs/ARCHITECTURE.md` — Mermaid system diagram, component descriptions, core data flows (A–H), security model, zero-retention invariant called out in bold.
- Created `rakshak/docs/RUNBOOK.md` — Operational procedures: DB reset, device registration, offline queue simulation, device revocation, log tailing, test execution, sample video download, full demo runner.
- Created `rakshak/docs/DEMO_SCRIPT.md` — Step-by-step judge demo with "Do this:" / "Say this:" format. Covers: login, empty hotlist, citizen complaint, cop approval, simulator hit, live map, analytics, revocation, privacy callout.
- Created `rakshak/docs/API.md` — Manual API reference mirroring FastAPI auto-generated `/docs`. Table per endpoint group with request/response schemas, auth requirements, and status codes.
- Updated `rakshak/docs/KNOWN_LIMITATIONS.md` — Comprehensive list of 27 items covering: prototype shortcuts (TFLite fallback, `/detect` endpoint), security deferrals, DB assumptions, scaling limitations, simulator constraints, frontend gaps, mobile app gaps, and architectural assumptions.