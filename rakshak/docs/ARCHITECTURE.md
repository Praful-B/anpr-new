# RAKSHAK — System Architecture

## System diagram

```mermaid
graph TB
    subgraph Mobile["Mobile Devices (Fleet & Volunteer)"]
        CAM[Camera] --> DETECT[On-device AI<br/>YOLO11n + OCR]
        DETECT --> MATCH{Plate matches<br/>hotlist?}
        MATCH -- No --> DISCARD[Discard frame<br/>No storage, no tx]
        MATCH -- Yes --> QUEUE[Local SQLite Queue]
        QUEUE --> FLUSH[Flush hits every 5s]
    end

    subgraph Backend["Backend (FastAPI)"]
        API[REST API /api/v1]
        SIGHTING_EP[/sightings endpoint]
        HOTLIST_EP[/hotlist/sync]
        WS[WebSocket<br/>/ws/dashboard]
        SCHED[APScheduler<br/>FIR expiry + nightly purge]
        DEDUP[Dedup + Throttle<br/>30s per device+plate<br/>90s cluster merge]
    end

    subgraph Storage["Storage"]
        DB[(PostgreSQL + PostGIS)]
        REDIS[(Redis<br/>Rate limits, cache)]
        OBJSTORE[Object Store<br/>Sighting photos]
    end

    subgraph Dashboard["Police Dashboard"]
        REACT[React SPA<br/>Vite + TailwindCSS]
        MAP[Leaflet Map<br/>+ Heatmap]
        CHARTS[Recharts Analytics]
        WSC[WebSocket Client<br/>Real-time updates]
    end

    subgraph Sync["Hotlist Sync"]
        SYNC_EP[/hotlist/sync]
        ENCRYPT[AES-256-GCM<br/>Encryption]
    end

    FLUSH -->|X-Device-Token| SIGHTING_EP
    SIGHTING_EP --> DEDUP
    DEDUP --> OBJSTORE
    DEDUP --> DB
    DB --> WS
    WS --> WSC
    WSC --> REACT
    REACT --> MAP
    REACT --> CHARTS

    SYNC_EP --> ENCRYPT
    ENCRYPT -->|encrypted plates| DETECT
    SCHED --> DB
    REDIS --> API
    DB --> SCHED
```

## Components

### Mobile devices (fleet & volunteer phones)

Every government fleet vehicle and volunteer citizen's phone runs the RAKSHAK mobile app (React Native + Expo). The app activates the camera, runs YOLO11n for plate detection, applies EasyOCR for text recognition, normalises the plate to the Indian format, and checks the plate against an in-memory hotlist set. The hotlist is downloaded encrypted (AES-256-GCM with a per-device HKDF-derived key) and decrypted only in memory during the matching loop. **Non-matching plates are discarded within one frame loop — no storage, no network transmission.**

### Backend (FastAPI + SQLAlchemy)

The Python backend handles user authentication (JWT), complaint lifecycle management, device registration, hotlist CRUD, sighting ingestion with throttle/dedup, analytics aggregation, and WebSocket broadcast to connected police dashboards. APScheduler runs two background jobs: FIR expiry (every 5 minutes) and nightly data purge.

### PostgreSQL + PostGIS

Primary data store for all structured data: users, complaints, hotlist entries, sightings, devices, and audit logs. PostGIS provides geospatial indexing for sighting location queries and heatmap aggregation. All tables use UUID primary keys and `created_at`/`updated_at` timestamps.

### Redis

Used for rate limiting (complaint submissions per user/IP, sighting ingestion per device/plate) and as a cache layer. In production, would also serve as the WebSocket broadcast backbone for horizontal scaling.

### Object store (photos)

Sighting photos are stored via a `StorageBackend` abstraction. The prototype uses local filesystem (`./data/uploads/`). Production deployments use S3/MinIO through the same interface. The database stores only the URL, never the blob.

### Police dashboard (React + Vite + Leaflet)

A single-page application served via nginx. Provides the hotlist table, vehicle detail view with sighting timeline, real-time Leaflet map with heatmap overlay, FIR verification workflow, analytics charts (Recharts), and admin user management. Connects to the backend via REST API and WebSocket for live updates.

### Device simulator

A CLI tool (`scripts/device_simulator.py`) that emulates the on-device detection pipeline for demo and testing. It processes a video file, runs YOLO + OCR, normalises plates, and sends hit events to the backend. Used for end-to-end demos and load testing.

---

## Core data flows

### Flow A: Complaint → Hotlist

Citizen registers → files complaint with plate → `POST /complaints` → status `PENDING_VERIFICATION`. COP reviews proof on dashboard → approves → complaint marked `VERIFIED`, hotlist entry created with status `ACTIVE_UNCONFIRMED` and 48-hour FIR deadline. WebSocket notification pushed to all connected COPs. Reject → status `REJECTED` with reason.

### Flow B: Hotlist sync to devices

Device authenticates via `X-Device-Token` → `GET /hotlist/sync` → receives `{version, iv, ciphertext, key_id}`. Device decrypts in memory using per-device AES-256-GCM key (HKDF-derived from master key) → loads plates into hash set → **never persists plaintext**.

### Flow C: On-device scanning (every 1 second)

1. Grab frame from camera
2. Quality filter: reject blur (Laplacian variance) and darkness (mean brightness < 40)
3. YOLO11n plate detection
4. Crop detected plate region
5. EasyOCR text recognition
6. Indian plate normalisation (uppercase, strip spaces, positional OCR correction)
7. Temporal voting: last 5 reads, accept when 3+ agree
8. Match against in-memory hotlist hash set
9. **On match:** compress JPEG, build hit event, enqueue locally, flush every 5 seconds
10. **On no match:** discard. No storage. No transmission.

### Flow D: Server hit ingestion

Device sends batched events → `POST /sightings` (authenticated via `X-Device-Token`). Server: validates payload, normalises plate, re-verifies against active hotlist in DB, applies throttle (30s per device+plate), assigns cluster (90s window), stores photo via `StorageBackend`, inserts sighting, updates hotlist `last_seen_*` fields, pushes WebSocket notification to COPs.

### Flow E: FIR verification

Citizen submits FIR reference → `POST /complaints/{id}/fir`. COP verifies FIR details → `PUT /hotlist/{id}` with `status: ACTIVE_CONFIRMED` and `fir_ref`. Scheduler no longer expires this entry.

### Flow F: Expiry and cooldown

APScheduler runs every 5 minutes: `ACTIVE_UNCONFIRMED` entries past `fir_deadline` → status `EXPIRED`, `cooldown_until = now + 7 days`. Nightly job (§10): purges rejected complaints > 30 days, expired/closed hotlist entries > 180 days past cooldown, sightings > 90 days (rows **and** their photo blobs, best-effort), and audit logs > 1 year.

### Flow G: Recovery

COP sets `status: CLOSED` via `PUT /hotlist/{id}` with `recovered_at: now` → WebSocket `hotlist_change` event → devices drop the plate on next sync.

### Flow H: Device revocation

Admin calls `POST /devices/{id}/revoke` → device marked `revoked` → next sync returns 401 → client wipes hotlist cache and local queue.

---

## Security model

- **JWT:** Access tokens (15 min) in memory only. Refresh tokens (7 days) in HttpOnly cookie (dashboard).
- **Passwords:** bcrypt cost factor 12.
- **Device tokens:** 32-byte URL-safe random, shown once at registration, stored bcrypt-hashed.
- **Hotlist encryption:** Per-device AES-256-GCM keys derived via HKDF from a master key. Hotlist decrypted only in memory, never shown in UI, remotely wipeable.
- **Rate limiting:** Redis-backed sliding window counters for complaint submission, sighting ingestion, and login attempts.
- **Audit logging:** Every COP/ADMIN write operation logged with actor, action, target, and metadata.

> **Zero-retention invariant:** The backend NEVER receives non-matching plates. This is the product's entire value proposition. Any code path that transmits an unmatched plate is a bug.
