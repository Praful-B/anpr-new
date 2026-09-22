# RAKSHAK — API Reference

> **Live source of truth:** The interactive Swagger docs are auto-generated at `http://localhost:8000/docs` when the backend is running. This document is a manual mirror for offline reference.

Base URL: `http://localhost:8000/api/v1`

Authentication: `Authorization: Bearer <jwt_access_token>` header (except auth endpoints and device endpoints which use `X-Device-Token`).

---

## Authentication

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| `POST` | `/auth/register` | None | Register a new user |
| `POST` | `/auth/login` | None | Login and receive JWT tokens |
| `POST` | `/auth/refresh` | Cookie / body | Refresh an expired access token |

### POST /auth/register

**Request body:**

```json
{
  "name": "string",
  "email": "string",
  "phone": "string | null",
  "password": "string (min 8 chars)",
  "role": "CITIZEN | VOLUNTEER | COP | ADMIN"
}
```

**Response:** `201 Created`

```json
{
  "user": {
    "id": "uuid",
    "name": "string",
    "email": "string",
    "phone": "string | null",
    "role": "CITIZEN",
    "created_at": "2026-01-01T00:00:00Z"
  },
  "tokens": {
    "access_token": "string",
    "refresh_token": "string",
    "token_type": "bearer"
  }
}
```

**Errors:** `409 Conflict` (duplicate email)

### POST /auth/login

**Request body:**

```json
{
  "email": "string",
  "password": "string"
}
```

**Response:** `200 OK` — Top-level `TokenResponse` fields (`access_token`,
`refresh_token`, `token_type`) plus `user` — not nested under a `tokens` key
as in register. Refresh token also set as `rakshak_refresh` HttpOnly cookie.

**Errors:** `401 Unauthorized`

### POST /auth/refresh

**Request body:** `{ "refresh_token": "string" }` — or use the `rakshak_refresh` cookie.

**Response:** `200 OK` — New `TokenResponse`.

**Errors:** `401 Unauthorized`

---

## Complaints

| Method | Endpoint | Auth | Role | Description |
|--------|----------|------|------|-------------|
| `POST` | `/complaints/` | Bearer JWT | CITIZEN, VOLUNTEER | File a complaint |
| `GET` | `/complaints/mine` | Bearer JWT | Any | List own complaints |
| `POST` | `/complaints/{id}/fir` | Bearer JWT | Owner | Submit FIR reference |
| `POST` | `/complaints/{id}/verify` | Bearer JWT | COP, ADMIN | Approve or reject complaint |

### POST /complaints/

**Request:** `multipart/form-data`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `plate` | string | Yes | Licence plate (normalised server-side) |
| `notes` | string | No | Additional notes |
| `proof` | file | No | Proof document (max 10 MB) |

**Response:** `201 Created` — `ComplaintResponse`

**Rate limits:** 3 per user per 24h, 10 per IP per 24h. Returns `429` with `Retry-After` header.

### GET /complaints/mine

**Response:** `200 OK` — `list[ComplaintResponse]`

### POST /complaints/{id}/fir

**Request body:**

```json
{
  "fir_ref": "string"
}
```

**Response:** `200 OK`

```json
{
  "fir_ref": "string",
  "hotlist_entry_id": "uuid"
}
```

**Errors:** `403 Forbidden` (not owner), `404 Not Found`, `409 Conflict` (already submitted)

### POST /complaints/{id}/verify

**Request body:**

```json
{
  "decision": "approve | reject",
  "reason": "string | null"
}
```

**Response:** `200 OK` — `ComplaintResponse` (status updated)

**Errors:** `400 Bad Request`, `403 Forbidden`, `404 Not Found`

---

## Hotlist

| Method | Endpoint | Auth | Role | Description |
|--------|----------|------|------|-------------|
| `GET` | `/hotlist/sync` | X-Device-Token | Device | Get encrypted hotlist |
| `GET` | `/hotlist/` | Bearer JWT | COP | List hotlist entries |
| `GET` | `/hotlist/{id}` | Bearer JWT | COP | Get hotlist detail |
| `PUT` | `/hotlist/{id}` | Bearer JWT | COP | Update hotlist entry |
| `DELETE` | `/hotlist/{id}` | Bearer JWT | COP | Soft-delete (close) entry |

### GET /hotlist/sync

**Header:** `X-Device-Token: <device_token>`

**Response:** `200 OK`

```json
{
  "version": 1,
  "iv": "base64",
  "ciphertext": "base64",
  "key_id": "string"
}
```

The ciphertext is an AES-256-GCM encrypted JSON array of plate strings. The device decrypts using its per-device HKDF-derived key.

**Errors:** `401 Unauthorized`

### GET /hotlist/

**Query parameters:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `plate` | string | — | Filter by plate (partial match) |
| `status` | string | — | Filter by status |
| `from_date` | date | 30 days ago | Start date |
| `to_date` | date | now | End date |
| `page` | int | 1 | Page number (min 1) |
| `per_page` | int | 20 | Results per page (1-100) |

**Response:** `200 OK` — `list[HotlistResponse]`

### GET /hotlist/{id}

**Response:** `200 OK` — `HotlistDetailResponse`

```json
{
  "id": "uuid",
  "plate": "MH12AB1234",
  "status": "ACTIVE_CONFIRMED",
  "complaint": { ... },
  "sightings": [ ... ],
  ...
}
```

Includes the associated complaint and last 50 sightings.

### PUT /hotlist/{id}

**Request body:**

```json
{
  "status": "ACTIVE_CONFIRMED | CLOSED | ...",
  "fir_ref": "string | null",
  "notes": "string | null",
  "dismissed": true | false,
  "recovered_at": "datetime | null",
  "fir_verified_at": "datetime | null"
}
```

**Response:** `200 OK` — `HotlistResponse`

### DELETE /hotlist/{id}

**Response:** `200 OK`

```json
{
  "id": "uuid",
  "status": "CLOSED"
}
```

Soft-delete: sets status to `CLOSED`.

---

## Devices

| Method | Endpoint | Auth | Role | Description |
|--------|----------|------|------|-------------|
| `POST` | `/devices/register` | Bearer JWT | Any | Register a new device |
| `POST` | `/devices/{id}/revoke` | Bearer JWT | ADMIN | Revoke a device |

### POST /devices/register

**Request body:**

```json
{
  "type": "FLEET | VOLUNTEER"
}
```

**Response:** `201 Created`

```json
{
  "device_id": "uuid",
  "device_token": "string (shown once)",
  "encryption_key_b64": "string"
}
```

**Important:** The `device_token` is shown only once at registration. Store it securely.

### POST /devices/{id}/revoke

**Response:** `200 OK` — `DeviceResponse` with `revoked: true`

**Errors:** `403 Forbidden` (not ADMIN), `404 Not Found`

---

## Sightings

| Method | Endpoint | Auth | Role | Description |
|--------|----------|------|------|-------------|
| `POST` | `/sightings/` | X-Device-Token | Device | Ingest hit events |
| `GET` | `/sightings/` | Bearer JWT | COP | List sightings |

### POST /sightings/

**Header:** `X-Device-Token: <device_token>`

**Request body:**

```json
{
  "events": [
    {
      "plate": "MH12AB1234",
      "lat": 19.076,
      "lng": 72.877,
      "captured_at": "2026-01-01T12:00:00Z",
      "confidence": 87,
      "photo_b64": "base64-encoded-jpeg..."
    }
  ]
}
```

**Response:** `200 OK`

```json
{
  "accepted": 1,
  "dropped": 0,
  "reasons": []
}
```

`reasons` holds one **`{index, reason}` object per dropped event** — `index`
is the event's zero-based position in the submitted `events` array, and
`reason` is one of `timestamp_out_of_tolerance`, `plate_not_hotlisted`, or
`throttled`, e.g. `[{"index": 0, "reason": "plate_not_hotlisted"}]`. The
submitted plate is never echoed back, logged, or stored when it does not match
an active hotlist entry (privacy invariant §2).

**Processing per event:**
1. Timestamp validation (must be within ±10 minutes of server time)
2. Plate normalisation
3. Hotlist match verification
4. Throttle check (1 accepted hit per device+plate per 30 seconds)
5. Cluster assignment (same hotlist_id within 90 seconds)
6. Photo storage via `StorageBackend`
7. Sighting insert
8. Hotlist `last_seen_*` update
9. WebSocket broadcast

### GET /sightings/

**Query parameters:**

| Param | Type | Description |
|-------|------|-------------|
| `plate` | string | Filter by plate |
| `from_date` | date | Start date |
| `to_date` | date | End date |

**Response:** `200 OK` — `list[SightingResponse]` (max 200)

---

## Analytics

All endpoints require COP or ADMIN role. Accept optional `from` and `to` query params (default: last 30 days).

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/analytics/overview` | Aggregate metrics |
| `GET` | `/analytics/heatmap` | Sighting locations on grid |
| `GET` | `/analytics/recovery-metrics` | Weekly recovery time series |
| `GET` | `/analytics/false-positive-rate` | Dismissed hits ratio |
| `GET` | `/analytics/device-coverage` | Per-device activity stats |
| `GET` | `/analytics/time-patterns` | Sightings by hour and day |

### GET /analytics/overview

```json
{
  "total_active_hotlist": 12,
  "total_sightings_last_24h": 5,
  "total_sightings_last_7d": 34,
  "total_recoveries_last_30d": 3,
  "avg_time_to_first_sighting_hours": 18.5,
  "avg_time_to_recovery_hours": 72.3
}
```

### GET /analytics/heatmap

```json
[
  { "lat": 19.076, "lng": 72.877, "weight": 15 },
  { "lat": 19.077, "lng": 72.878, "weight": 3 }
]
```

Locations rounded to 3 decimal places (~100m grid cells).

### GET /analytics/recovery-metrics

```json
[
  {
    "week_start": "2026-01-06",
    "hotlist_added": 5,
    "recovered": 2,
    "expired": 1,
    "recovery_rate": 0.40
  }
]
```

### GET /analytics/false-positive-rate

```json
{
  "total_hits": 150,
  "hits_dismissed_by_officer": 12,
  "fp_rate": 0.08,
  "per_device": [
    { "device_id": "uuid", "total_hits": 100, "hits_dismissed": 5, "fp_rate": 5.0 }
  ]
}
```

### GET /analytics/device-coverage

```json
{
  "total": 25,
  "active_last_24h": 18,
  "revoked": 2,
  "devices": [
    { "device_id": "uuid", "type": "FLEET", "total_sightings": 45, "last_active": "2026-01-15T10:30:00Z" }
  ]
}
```

### GET /analytics/time-patterns

`by_hour` runs from 00:00 to 23:00 UTC; `by_day` starts at Sunday (index 0) and
ends at Saturday (index 6).

```json
{
  "by_hour": [0, 2, 5, 12, 20, 35, 40, 45, 30, 25, 18, 15, 14, 16, 22, 28, 38, 42, 50, 48, 40, 30, 15, 5],
  "by_day": [12, 18, 22, 20, 25, 30, 15]
}
```

---

## Detection (prototype fallback)

| Method | Endpoint | Auth | Role | Description |
|--------|----------|------|------|-------------|
| `POST` | `/detect` | X-Device-Token | Device | Server-side plate detection |

> **WARNING:** This endpoint exists only as a prototype fallback for the mobile app when on-device TFLite integration is not available. It transmits raw camera frames to the server, which **violates the zero-retention privacy promise**. Remove before production deployment.

---

## WebSocket

| Endpoint | Auth | Events |
|----------|------|--------|
| `/ws/dashboard?token=<jwt>` | Bearer JWT in query param | `new_sighting`, `hotlist_change`, `connected`, `ping` |

**Event format:**

```json
{
  "type": "new_sighting",
  "data": {
    "sighting_id": "uuid",
    "plate": "MH12AB1234",
    "lat": 19.076,
    "lng": 72.877,
    "captured_at": "2026-01-01T12:00:00Z",
    "confidence": 87,
    "photo_url": "string"
  }
}
```

**Heartbeat:** Server sends `ping` every 30 seconds. Client should respond with `pong`.

---

## Health check

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| `GET` | `/healthz` | None | Service health |

**Response:** `200 OK`

```json
{
  "status": "ok",
  "version": "0.1.0"
}
```
