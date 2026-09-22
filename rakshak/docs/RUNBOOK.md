# RAKSHAK — Operations Runbook

## Table of contents

1. [Reset database](#reset-database)
2. [Add a device](#add-a-device)
3. [Simulate offline queue](#simulate-offline-queue)
4. [Revoke a device](#revoke-a-device)
5. [Tail logs](#tail-logs)
6. [Run tests](#run-tests)
7. [Download sample videos](#download-sample-videos)
8. [Run the full demo](#run-the-full-demo)

---

## Reset database

Drop all tables, re-run migrations, and re-seed.

```bash
# 1. Drop and recreate the database
docker compose exec postgres psql -U postgres -d rakshak \
  -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
docker compose exec postgres psql -U postgres -d rakshak \
  -c "CREATE EXTENSION IF NOT EXISTS postgis;"

# 2. Re-run Alembic migrations
docker compose exec backend alembic upgrade head

# 3. Re-seed users and demo data
docker compose exec backend python scripts/seed_db.py
```

**Alternative (nuclear option):** Stop containers, delete the `pgdata` volume, and restart.

```bash
docker compose down -v
docker compose up --build -d
# Wait for health checks, then seed
docker compose exec backend python scripts/seed_db.py
```

---

## Add a device

Devices represent fleet vehicles or volunteer phones that run the ANPR scanner.

### Via API

```bash
# 1. Register as any user first, then register a device
TOKEN="<your-jwt-access-token>"

curl -X POST http://localhost:8000/api/v1/devices/register \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"type": "VOLUNTEER"}'
# Returns: {"device_id": "...", "device_token": "...", "encryption_key_b64": "..."}
# Save the device_token — it is shown only once.
```

### Via device simulator (auto-registration)

```bash
python scripts/device_simulator.py \
  --video data/samples/sample1.mp4 \
  --plate MH12AB1234 \
  --device-email volunteer@rakshak.local \
  --device-password Vol@12345
```

The simulator automatically registers a device if no `--device-token` is provided.

---

## Simulate offline queue

The device simulator queues hits in a local SQLite database when the backend is unreachable, then flushes on reconnection.

```bash
# 1. Stop the backend to simulate network loss
docker compose stop backend

# 2. Run the simulator — hits will queue locally
python scripts/device_simulator.py \
  --video data/samples/sample1.mp4 \
  --plate MH12AB1234 \
  --device-email volunteer@rakshak.local \
  --device-password Vol@12345

# 3. Restart the backend — queued hits will flush
docker compose start backend
# Watch the backend logs to see queued hits being ingested
```

---

## Revoke a device

Device revocation prevents a compromised device from receiving new hotlist data.

```bash
# Requires ADMIN role
ADMIN_TOKEN="<your-admin-jwt-token>"
DEVICE_ID="<uuid-of-device-to-revoke>"

curl -X POST "http://localhost:8000/api/v1/devices/${DEVICE_ID}/revoke" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
# Returns: {"id": "...", "revoked": true, ...}
```

The revoked device will receive a 401 on its next hotlist sync and should wipe its local hotlist cache and offline queue.

---

## Tail logs

### Backend logs (structured JSON)

```bash
docker compose logs -f backend
```

### All services

```bash
docker compose logs -f
```

### PostgreSQL logs

```bash
docker compose logs -f postgres
```

### Redis logs

```bash
docker compose logs -f redis
```

---

## Run tests

The test suite uses pytest with httpx AsyncClient. External services (PostgreSQL, Redis) are mocked with in-memory fakes.

```bash
# Run from the rakshak/ directory
cd rakshak

# Run all tests
docker compose exec backend pytest -v

# Run a specific test file
docker compose exec backend pytest tests/test_crypto.py -v

# Run with coverage
docker compose exec backend pytest --cov=app --cov-report=term-missing
```

### Running tests locally (without Docker)

```bash
cd rakshak/backend

# Install dependencies
pip install -r requirements.txt

# Run tests (uses SQLite + FakeRedis automatically)
pytest -v
```

---

## Download sample videos

```bash
bash scripts/download_sample_videos.sh
```

Downloads sample videos to `data/samples/` for use with the device simulator.

---

## Run the full demo

```bash
bash scripts/run_demo.sh
```

This script:
1. Seeds the database
2. Downloads sample videos if not present
3. Runs the device simulator against `sample1.mp4` targeting plate `MH12AB1234`
4. Tails backend logs

---

## Service health checks

```bash
# Backend
curl http://localhost:8000/healthz
# → {"status":"ok","version":"0.1.0"}

# PostgreSQL
docker compose exec postgres pg_isready -U postgres

# Redis
docker compose exec redis redis-cli ping
# → PONG

# Dashboard
curl -s -o /dev/null -w "%{http_code}" http://localhost:5173
# → 200
```
