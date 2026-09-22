/**
 * @module hitHistory
 * Persistent "Recent Hits" store for the volunteer app.
 *
 * Every hotlist match is written here so the volunteer can review what the
 * scanner saw, when, where, and whether the backend accepted it. Only matched
 * plates ever reach this store; unmatched detections are discarded on-device
 * and never recorded.
 */

import * as SQLite from "expo-sqlite";
import type { HitDeliveryStatus } from "./queue";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** Database name for the recent-hits store. */
const DB_NAME = "rakshak_history.db";

/** Default number of hits returned by {@link listRecentHits}. */
export const DEFAULT_HISTORY_LIMIT = 50;

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** A single recorded hotlist hit. */
export interface RecentHit {
  /** Auto-incremented row id. */
  id: number;
  /** Normalised plate string that matched the hotlist. */
  plate: string;
  /** Latitude reported at capture time, or null when unavailable. */
  lat: number | null;
  /** Longitude reported at capture time, or null when unavailable. */
  lng: number | null;
  /** ISO-8601 UTC capture timestamp. */
  captured_at: string;
  /** OCR confidence score (0-100). */
  confidence: number;
  /** Delivery status at the time of the last update. */
  status: HitDeliveryStatus;
  /** Local file URI of the captured frame thumbnail, if any. */
  thumbnail_uri: string | null;
}

// ---------------------------------------------------------------------------
// Database
// ---------------------------------------------------------------------------

let _db: SQLite.SQLiteDatabase | null = null;

/**
 * Open (or reuse) the recent-hits database and ensure its table exists.
 *
 * @returns The opened SQLite database instance.
 */
async function getDb(): Promise<SQLite.SQLiteDatabase> {
  if (_db) return _db;
  _db = await SQLite.openDatabaseAsync(DB_NAME);
  await _db.execAsync(`
    CREATE TABLE IF NOT EXISTS recent_hits (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      plate TEXT NOT NULL,
      lat REAL,
      lng REAL,
      captured_at TEXT NOT NULL,
      confidence INTEGER NOT NULL,
      status TEXT NOT NULL,
      thumbnail_uri TEXT
    );
  `);
  return _db;
}

// ---------------------------------------------------------------------------
// Writes
// ---------------------------------------------------------------------------

/**
 * Record a new hit and return its row id.
 *
 * @param hit - The hit fields to persist (without the row id).
 * @returns The auto-generated row id.
 */
export async function recordHit(
  hit: Omit<RecentHit, "id">
): Promise<number> {
  const db = await getDb();
  const result = await db.runAsync(
    `INSERT INTO recent_hits
       (plate, lat, lng, captured_at, confidence, status, thumbnail_uri)
     VALUES (?, ?, ?, ?, ?, ?, ?)`,
    [
      hit.plate,
      hit.lat,
      hit.lng,
      hit.captured_at,
      hit.confidence,
      hit.status,
      hit.thumbnail_uri,
    ]
  );
  return result.lastInsertRowId;
}

/**
 * Update the delivery status of a previously recorded hit.
 *
 * @param id - Row id returned by {@link recordHit}.
 * @param status - The new delivery status.
 */
export async function updateHitStatus(
  id: number,
  status: HitDeliveryStatus
): Promise<void> {
  const db = await getDb();
  await db.runAsync("UPDATE recent_hits SET status = ? WHERE id = ?", [
    status,
    id,
  ]);
}

// ---------------------------------------------------------------------------
// Reads
// ---------------------------------------------------------------------------

/**
 * List the most recent hits, newest first.
 *
 * @param limit - Maximum number of rows to return.
 * @returns The recorded hits.
 */
export async function listRecentHits(
  limit: number = DEFAULT_HISTORY_LIMIT
): Promise<RecentHit[]> {
  const db = await getDb();
  return db.getAllAsync<RecentHit>(
    "SELECT * FROM recent_hits ORDER BY id DESC LIMIT ?",
    [limit]
  );
}

/**
 * Delete every recorded hit. Used on logout and device revocation.
 */
export async function clearRecentHits(): Promise<void> {
  const db = await getDb();
  await db.runAsync("DELETE FROM recent_hits");
}
