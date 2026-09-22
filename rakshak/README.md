# RAKSHAK -- 

**Privacy-first mobile ANPR network for stolen vehicle detection.**

Citizens file complaints. After police verification, the plate goes on an encrypted hotlist synced to fleet and volunteer phones. On-device AI scans plates in real time. When a scanned plate matches the hotlist, its location, photo, and timestamp reach a police dashboard in near real time. **Non-matching plates are never stored, never transmitted.**

---

## Quick start (5 minutes)

### Prerequisites

- Docker and Docker Compose v2 (`docker compose`)
- `curl` (for the health checks `make up` performs)
- ~2 GB disk space for Docker images
- For the device simulator only: Python 3.11+ and `pip install -r scripts/requirements-simulator.txt`

### 1. Clone and configure

```bash
git clone <repo-url> rakshak
cd rakshak
cp .env.example .env
```

`.env.example` ships a **development** `MASTER_KEY_B64` so the stack works out of the box. Replace it before any real deployment:

```bash
python3 -c "import secrets,base64; print('MASTER_KEY_B64=' + base64.b64encode(secrets.token_bytes(32)).decode())"
# paste the output over the MASTER_KEY_B64 line in .env
```

### 2. Start the stack

```bash
make up          # docker compose up --build -d, then waits for /healthz
```

This starts PostGIS, Redis, the FastAPI backend (running Alembic migrations first), and the React dashboard. `make up` polls `http://localhost:8000/healthz` and reports when the backend is healthy.

```bash
curl http://localhost:8000/healthz
# → {"status":"ok","version":"0.1.0"}
```

### 3. Seed the database

```bash
make seed
```

This creates four test users and a sample hotlisted plate (`MH12AB1234`):

| Role | Email | Password |
|------|-------|----------|
| Admin | `admin@rakshak.local` | `Admin@123` |
| Cop | `cop@rakshak.local` | `Cop@12345` |
| Citizen | `citizen@rakshak.local` | `Cit@12345` |
| Volunteer | `volunteer@rakshak.local` | `Vol@12345` |

### 4. Open the dashboard

Open [http://localhost:5173](http://localhost:5173) in your browser and log in as **cop** (`cop@rakshak.local` / `Cop@12345`). The hotlist page lists the seeded `MH12AB1234` entry.

### 5. Run the device simulator

The simulator runs on the host (it loads YOLO and EasyOCR locally) and talks to the backend on port 8000.

```bash
pip install -r scripts/requirements-simulator.txt   # once
bash scripts/download_sample_videos.sh             # if data/samples is empty

python3 scripts/device_simulator.py \
  --video data/samples/sample1.mp4 \
  --plate MH12AB1234 \
  --device-email volunteer@rakshak.local \
  --device-password Vol@12345 \
  --lat 19.0760 \
  --lng 72.8777
```

`make demo` performs the seed, the sample download, and this simulator command in one step.

### 6. See the hit on the dashboard

Within 5 seconds of the simulator detecting the plate, a toast notification appears over the dashboard and the sighting shows up on the hotlist detail page with its location, timestamp, and confidence score.

### 7. Explore analytics

Navigate to the Analytics page to see overview metrics (active hotlist, sightings, recoveries), the sighting heatmap on Leaflet, hourly/daily time patterns, false-positive rate per device, and device coverage.

---

## Makefile commands

| Command | What it does |
|---------|--------------|
| `make up` | Build and start postgres, redis, backend, dashboard; waits for health |
| `make down` | Stop the stack **and delete its volumes** (fresh database next `make up`) |
| `make seed` | Create the demo users and the `MH12AB1234` hotlist entry |
| `make demo` | Seed, ensure sample videos, then run the device simulator |
| `make test` | Run the backend pytest suite inside the backend container |
| `make lint` | Audit Python docstrings/function lengths and typecheck dashboard + mobile |
| `make migrate` | Apply Alembic migrations inside the container |
| `make logs` | Follow the compose logs |

`make` with no target prints the same list.

---

## Architecture overview

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  Mobile App  │────▶│   Backend    │────▶│  PostgreSQL   │
│ (Expo/React  │     │  (FastAPI)   │     │   + PostGIS   │
│   Native)    │     │              │     └──────────────┘
└──────────────┘     │  ┌────────┐  │     ┌──────────────┐
       ▲              │  │ Redis  │◀─┼────▶│   Dashboard  │
       │              │  └────────┘  │     │  (React+Vite)│
       │              └──────┬───────┘     └──────────────┘
       │                     │
  On-device AI        ┌──────┴───────┐
  (TFLite)            │  Scheduler   │
                      │ (APScheduler)│
                      └──────────────┘
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full Mermaid diagram and component descriptions.

---

## Project structure

```
rakshak/
├── backend/           # FastAPI + SQLAlchemy + Alembic
│   ├── app/           # Application code (API, models, schemas, services)
│   ├── alembic/       # Database migrations
│   ├── tests/         # Pytest test suite (128 tests)
│   └── Dockerfile
├── mobile/            # React Native + Expo mobile app
│   └── src/           # Screens, services, AI inference, auth store
├── dashboard/         # React + Vite + TailwindCSS + Leaflet
│   ├── src/           # Pages, components, WebSocket client
│   └── .env.example   # VITE_API_URL / VITE_PROXY_TARGET
├── scripts/           # Device simulator, seed script, demo runner, audit
├── data/              # Sample videos, uploaded photos
├── docs/              # Architecture, API reference, runbook, demo script
├── Makefile
├── docker-compose.yml
├── .env.example
└── README.md
```

---

## API documentation

The backend exposes a REST API under `/api/v1`. Interactive Swagger docs are available at [http://localhost:8000/docs](http://localhost:8000/docs) while the backend is running.

See [docs/API.md](docs/API.md) for a manual endpoint reference.

---

## Configuration

| File | Purpose |
|------|---------|
| `.env` | Backend + Postgres + Redis credentials and tunables ([`.env.example`](.env.example)) |
| `dashboard/.env` | `VITE_API_URL` (relative `/api/v1` is proxied) and `VITE_PROXY_TARGET` for local dev |
| `mobile/.env` | `EXPO_PUBLIC_API_URL` — the backend URL reachable from the device |

Every variable is documented in the matching `.env.example`.

---

## Tech stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.11, FastAPI, SQLAlchemy 2.x, Alembic |
| Database | PostgreSQL 15 + PostGIS |
| Cache/Queue | Redis 7 |
| Auth | JWT (python-jose), bcrypt (passlib) |
| Crypto | AES-256-GCM, HKDF (cryptography) |
| Scheduler | APScheduler |
| CV/OCR | YOLO11n (ultralytics), EasyOCR |
| Mobile | React Native + Expo (managed) |
| Dashboard | React 18, TypeScript, Vite, TailwindCSS, Leaflet, Recharts |
| Infra | Docker Compose |

---

## Core privacy promise

> **The backend NEVER receives non-matching plates. Ever.** Devices perform on-device matching against an encrypted hotlist. Only confirmed matches are transmitted. Unmatched detections are discarded within one frame loop, on-device, and the ingestion response reports a reason code rather than echoing the submitted plate.

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `make up` never reports healthy | `make logs`; the backend applies Alembic migrations before serving traffic |
| Dashboard shows a connection error | Check `curl http://localhost:8000/healthz`, then reload the page |
| WebSocket events never arrive | The dashboard proxies `/ws/` to the backend — confirm the dashboard container is rebuilt (`make up`) |
| Simulator exits with missing modules | `pip install -r scripts/requirements-simulator.txt` |
| No sighting appears | Confirm `MH12AB1234` is on the hotlist (`make seed`) and check `make logs` for ingestion errors |

---

## License

Proprietary — for demonstration purposes only.
