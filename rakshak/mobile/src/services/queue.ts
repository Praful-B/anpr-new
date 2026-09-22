/**
 * @module queue
 * SQLite-backed offline queue for hit events.
 *
 * When the device is offline or the server rejects a flush, hit events are
 * persisted in expo-sqlite. On reconnect, queued events are flushed to the
 * server with exponential backoff (1s, 2s, 4s, 8s, max 30s).
 */

import * as SQLite from "expo-sqlite";
import { deviceApiRequest, ApiError } from "./api";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** Database name for the offline queue. */
const DB_NAME = "rakshak_queue.db";

/** Maximum number of flush retries before giving up on an event. */
const MAX_FLUSH_RETRIES = 5;

/** Initial backoff delay in milliseconds. */
const INITIAL_BACKOFF_MS = 1000;

/** Maximum backoff delay in milliseconds. */
const MAX_BACKOFF_MS = 30000;

/** Maximum number of events to flush in a single batch. */
const FLUSH_BATCH_SIZE = 20;

/** Drop reason returned by the backend when a hit is inside the throttle window. */
const REASON_THROTTLED = "throttled";

/** Delivery outcome reported back to the scanner UI. */
export type HitDeliveryStatus =
  | "sending"
  | "sent"
  | "throttled"
  | "rejected"
  | "queued";

/** Batch response body returned by POST /api/v1/sightings/. */
interface IngestResponse {
  /** Number of events accepted and stored. */
  accepted: number;
  /** Number of events dropped. */
  dropped: number;
  /** Machine-readable drop reasons (never contains plate strings). */
  reasons: string[];
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** Shape of a hit event stored in the queue. */
export interface QueuedHitEvent {
  /** Unique queue row ID. */
  id: number;
  /** Plate number (normalised). */
  plate: string;
  /** Latitude of detection. */
  lat: number;
  /** Longitude of detection. */
  lng: number;
  /** ISO 8601 UTC timestamp of detection. */
  captured_at: string;
  /** OCR confidence score (0-100). */
  confidence: number;
  /** Base64-encoded JPEG photo. */
  photo_b64: string;
  /** Number of flush attempts so far. */
  retry_count: number;
  /** ISO 8601 timestamp of last flush attempt. */
  last_attempt_at: string | null;
}

// ---------------------------------------------------------------------------
// Database initialisation
// ---------------------------------------------------------------------------

let _db: SQLite.SQLiteDatabase | null = null;

/**
 * Open (or return cached) reference to the SQLite queue database.
 *
 * Creates the ``hit_queue`` table if it does not exist.
 *
 * @returns The opened SQLite database instance.
 */
async function getDb(): Promise<SQLite.SQLiteDatabase> {
  if (_db) return _db;
  _db = await SQLite.openDatabaseAsync(DB_NAME);
  await _db.execAsync(`
    CREATE TABLE IF NOT EXISTS hit_queue (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      plate TEXT NOT NULL,
      lat REAL NOT NULL,
      lng REAL NOT NULL,
      captured_at TEXT NOT NULL,
      confidence INTEGER NOT NULL,
      photo_b64 TEXT NOT NULL,
      retry_count INTEGER NOT NULL DEFAULT 0,
      last_attempt_at TEXT
    );
  `);
  return _db;
}

// ---------------------------------------------------------------------------
// Enqueue
// ---------------------------------------------------------------------------

/**
 * Persist a hit event in the local SQLite queue.
 *
 * @param event - The hit event to enqueue (without id/retry fields).
 * @returns The auto-generated queue row id.
 */
export async function enqueueHit(
  event: Omit<QueuedHitEvent, "id" | "retry_count" | "last_attempt_at">
): Promise<number> {
  const db = await getDb();
  const result = await db.runAsync(
    `INSERT INTO hit_queue (plate, lat, lng, captured_at, confidence, photo_b64)
     VALUES (?, ?, ?, ?, ?, ?)`,
    [event.plate, event.lat, event.lng, event.captured_at, event.confidence, event.photo_b64]
  );
  return result.lastInsertRowId;
}

/**
 * Submit one queued hit immediately and report its delivery outcome.
 *
 * On a definitive server answer (accepted, throttled, or otherwise rejected,
 * including 4xx responses) the row is removed so it is never retried. On a
 * network or 5xx failure the row is kept for the background flush loop.
 *
 * @param id          - Queue row id returned by {@link enqueueHit}.
 * @param deviceToken - The device authentication token.
 * @returns The delivery status for the scanner UI.
 */
export async function submitQueuedHit(
  id: number,
  deviceToken: string
): Promise<HitDeliveryStatus> {
  const db = await getDb();
  const row = await db.getFirstAsync<QueuedHitEvent>(
    "SELECT * FROM hit_queue WHERE id = ?",
    [id]
  );

  if (!row) {
    return "sent";
  }

  const status = await postHit(row, deviceToken);

  if (status === "queued") {
    const backoff = calculateBackoff(row.retry_count);
    await db.runAsync(
      `UPDATE hit_queue
       SET retry_count = retry_count + 1, last_attempt_at = ?
       WHERE id = ?`,
      [new Date(Date.now() + backoff).toISOString(), id]
    );
    return status;
  }

  await db.runAsync("DELETE FROM hit_queue WHERE id = ?", [id]);
  return status;
}

// ---------------------------------------------------------------------------
// Flush
// ---------------------------------------------------------------------------

/**
 * Flush queued hit events to the server with exponential backoff.
 *
 * Processes events in batches of {@link FLUSH_BATCH_SIZE}. For each event,
 * attempts to POST to ``/sightings`` with the device token. On success,
 * deletes the event from the queue. On failure, increments the retry count
 * and backs off exponentially.
 *
 * @param deviceToken - The device authentication token.
 * @returns Number of events successfully flushed.
 */
export async function flushQueue(deviceToken: string): Promise<number> {
  const db = await getDb();
  const rows = await db.getAllAsync<QueuedHitEvent>(
    `SELECT * FROM hit_queue
     WHERE retry_count < ?
     ORDER BY id ASC
     LIMIT ?`,
    [MAX_FLUSH_RETRIES, FLUSH_BATCH_SIZE]
  );

  if (rows.length === 0) return 0;

  let flushed = 0;

  for (const row of rows) {
    const success = await flushSingleEvent(row, deviceToken);
    if (success) {
      await db.runAsync("DELETE FROM hit_queue WHERE id = ?", [row.id]);
      flushed += 1;
    } else {
      const backoff = calculateBackoff(row.retry_count);
      const nextAttempt = new Date(Date.now() + backoff).toISOString();
      await db.runAsync(
        `UPDATE hit_queue
         SET retry_count = retry_count + 1, last_attempt_at = ?
         WHERE id = ?`,
        [nextAttempt, row.id]
      );
    }
  }

  return flushed;
}

/**
 * Flush a single queued event to the server.
 *
 * @param row         - The queued event to flush.
 * @param deviceToken - The device authentication token.
 * @returns True when the event reached a terminal state and should be removed.
 */
async function flushSingleEvent(
  row: QueuedHitEvent,
  deviceToken: string
): Promise<boolean> {
  const status = await postHit(row, deviceToken);
  return status !== "queued";
}

/**
 * POST one hit event and classify the outcome.
 *
 * @param row         - The queued event to send.
 * @param deviceToken - The device authentication token.
 * @returns The classified delivery status.
 */
async function postHit(
  row: QueuedHitEvent,
  deviceToken: string
): Promise<HitDeliveryStatus> {
  try {
    const response = (await deviceApiRequest("/sightings/", deviceToken, {
      method: "POST",
      body: JSON.stringify({
        events: [
          {
            plate: row.plate,
            lat: row.lat,
            lng: row.lng,
            captured_at: new Date(row.captured_at).toISOString(),
            confidence: row.confidence,
            photo_b64: row.photo_b64,
          },
        ],
      }),
    })) as IngestResponse;

    if (response.accepted > 0) {
      return "sent";
    }
    if (response.reasons.includes(REASON_THROTTLED)) {
      return "throttled";
    }
    return "rejected";
  } catch (err) {
    if (err instanceof ApiError && err.status >= 400 && err.status < 500) {
      return "rejected";
    }
    return "queued";
  }
}

/**
 * Calculate exponential backoff delay for a given retry count.
 *
 * @param retryCount - Current number of retries (0-indexed).
 * @returns Delay in milliseconds.
 */
function calculateBackoff(retryCount: number): number {
  const delay = INITIAL_BACKOFF_MS * Math.pow(2, retryCount);
  return Math.min(delay, MAX_BACKOFF_MS);
}

// ---------------------------------------------------------------------------
// Queue status
// ---------------------------------------------------------------------------

/**
 * Get the count of pending events in the queue.
 *
 * @returns Number of events waiting to be flushed.
 */
export async function getQueueSize(): Promise<number> {
  const db = await getDb();
  const result = await db.getFirstAsync<{ count: number }>(
    "SELECT COUNT(*) as count FROM hit_queue WHERE retry_count < ?",
    [MAX_FLUSH_RETRIES]
  );
  return result?.count ?? 0;
}

/**
 * Clear all events from the queue (used on device revocation).
 */
export async function clearQueue(): Promise<void> {
  const db = await getDb();
  await db.runAsync("DELETE FROM hit_queue");
}
