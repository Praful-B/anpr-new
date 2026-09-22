/**
 * @module hotlist
 * Hotlist sync service — fetches encrypted hotlist from the server,
 * decrypts it in memory with a per-device key from expo-secure-store,
 * and maintains an in-memory HashSet for fast plate matching.
 *
 * Syncs on app start and every 15 minutes. The hotlist plaintext is
 * never written to disk or exposed in the UI (see §3.1 of PROJECT_INFO.md).
 */

import * as SecureStore from "expo-secure-store";
import { apiRequest, ApiError } from "./api";
import { decryptAesGcm } from "./crypto";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** SecureStore key for the per-device AES-256-GCM encryption key (base64). */
const SECURE_STORE_DEVICE_KEY = "rakshak_device_encryption_key";

/** Sync interval in milliseconds (15 minutes). */
const SYNC_INTERVAL_MS = 15 * 60 * 1000;

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** Shape of the encrypted hotlist sync payload from the server. */
interface HotlistSyncPayload {
  /** Version integer (epoch timestamp) for change detection. */
  version: number;
  /** Base64-encoded 12-byte IV for AES-256-GCM decryption. */
  iv: string;
  /** Base64-encoded AES-256-GCM ciphertext. */
  ciphertext: string;
  /** Identifier of the device key used for encryption (device UUID). */
  key_id: string;
}

/** Internal state of the hotlist module. */
interface HotlistState {
  /** Set of normalised plate strings for O(1) lookup. */
  plates: Set<string>;
  /** Current version number (0 = not yet synced). */
  version: number;
  /** ID of the currently active sync interval. */
  syncTimerId: ReturnType<typeof setInterval> | null;
  /** Epoch milliseconds of the last successful sync (0 = never). */
  lastSyncAt: number;
}

// ---------------------------------------------------------------------------
// Module state
// ---------------------------------------------------------------------------

const _state: HotlistState = {
  plates: new Set<string>(),
  version: 0,
  syncTimerId: null,
  lastSyncAt: 0,
};

// ---------------------------------------------------------------------------
// Key management
// ---------------------------------------------------------------------------

/**
 * Store the device encryption key in expo-secure-store.
 *
 * @param keyBase64 - Base64-encoded 32-byte AES-256 key.
 */
export async function storeDeviceKey(keyBase64: string): Promise<void> {
  await SecureStore.setItemAsync(SECURE_STORE_DEVICE_KEY, keyBase64);
}

/**
 * Retrieve the device encryption key from expo-secure-store.
 *
 * @returns Base64-encoded key, or null if not stored.
 */
async function getDeviceKey(): Promise<string | null> {
  return SecureStore.getItemAsync(SECURE_STORE_DEVICE_KEY);
}

/**
 * Remove the device encryption key from expo-secure-store.
 * Used on device revocation.
 */
export async function clearDeviceKey(): Promise<void> {
  await SecureStore.deleteItemAsync(SECURE_STORE_DEVICE_KEY);
}

// ---------------------------------------------------------------------------
// Sync
// ---------------------------------------------------------------------------

/**
 * Fetch and decrypt the hotlist from the server, updating the in-memory set.
 *
 * Only updates if the server returns a newer version than currently cached.
 *
 * @returns True if the hotlist was updated, false if already current.
 */
export async function syncHotlist(): Promise<boolean> {
  const deviceKey = await getDeviceKey();
  if (!deviceKey) {
    return false;
  }

  try {
    const payload = (await apiRequest("/hotlist/sync")) as HotlistSyncPayload;

    if (payload.version <= _state.version) {
      return false;
    }

    const plaintext = await decryptAesGcm(
      payload.iv,
      payload.ciphertext,
      deviceKey
    );

    const plates: string[] = JSON.parse(plaintext);
    _state.plates = new Set(plates);
    _state.version = payload.version;
    _state.lastSyncAt = Date.now();

    return true;
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) {
      // Device revoked — clear local state.
      _state.plates = new Set();
      _state.version = 0;
      await clearDeviceKey();
    }
    return false;
  }
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Check whether a normalised plate is in the current hotlist.
 *
 * @param plate - Normalised plate string (uppercase, no spaces/hyphens).
 * @returns True if the plate matches a hotlist entry.
 */
export function isHotlisted(plate: string): boolean {
  return _state.plates.has(plate);
}

/**
 * Get the current hotlist version.
 *
 * @returns Version number (0 = not synced).
 */
export function getHotlistVersion(): number {
  return _state.version;
}

/**
 * Get the number of plates currently in the hotlist.
 *
 * @returns Count of hotlisted plates.
 */
export function getHotlistSize(): number {
  return _state.plates.size;
}

/**
 * Get the epoch-millisecond timestamp of the last successful hotlist sync.
 *
 * @returns Epoch milliseconds, or 0 when the hotlist has never synced.
 */
export function getLastSyncAt(): number {
  return _state.lastSyncAt;
}

/**
 * Snapshot the currently synced hotlist plates.
 *
 * Returns a copy so callers cannot mutate the in-memory set. The plaintext
 * never leaves this module except through this in-memory snapshot.
 *
 * @returns The plate strings currently loaded for matching.
 */
export function getHotlistPlates(): string[] {
  return Array.from(_state.plates);
}

/**
 * Start automatic hotlist sync on app start and every 15 minutes.
 */
export function startAutoSync(): void {
  if (_state.syncTimerId !== null) return;

  // Initial sync attempt (fire and forget).
  syncHotlist().catch(() => {
    // Silent — will retry on interval.
  });

  _state.syncTimerId = setInterval(() => {
    syncHotlist().catch(() => {
      // Silent — will retry on next interval.
    });
  }, SYNC_INTERVAL_MS);
}

/**
 * Stop automatic hotlist sync.
 */
export function stopAutoSync(): void {
  if (_state.syncTimerId !== null) {
    clearInterval(_state.syncTimerId);
    _state.syncTimerId = null;
  }
}

/**
 * Clear all hotlist state (used on logout or device revocation).
 */
export function clearHotlist(): void {
  _state.plates = new Set();
  _state.version = 0;
  _state.lastSyncAt = 0;
}
