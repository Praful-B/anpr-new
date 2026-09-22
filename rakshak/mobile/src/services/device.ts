/**
 * @module device
 * Device lifecycle for the mobile app.
 *
 * The backend authenticates hotlist sync and sighting ingestion with an
 * ``X-Device-Token`` header, not the user's JWT. This module registers the
 * phone once against the logged-in account, persists the one-time device
 * token and the per-device AES key in expo-secure-store, and clears both on
 * revocation.
 */

import * as SecureStore from "expo-secure-store";
import { apiRequest } from "./api";
import { storeDeviceKey, clearDeviceKey, clearHotlist } from "./hotlist";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** SecureStore key for the device authentication token. */
const SECURE_STORE_DEVICE_TOKEN = "rakshak_device_token";

/** SecureStore key for the registered device UUID. */
const SECURE_STORE_DEVICE_ID = "rakshak_device_id";

/** Device type registered by the mobile app. */
const MOBILE_DEVICE_TYPE = "VOLUNTEER";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** Response body of POST /api/v1/devices/register. */
interface DeviceRegisterResponse {
  /** UUID of the newly registered device. */
  device_id: string;
  /** One-time device token; not retrievable again. */
  device_token: string;
  /** Base64-encoded per-device AES-256 key. */
  encryption_key_b64: string;
}

// ---------------------------------------------------------------------------
// SecureStore helpers
// ---------------------------------------------------------------------------

/**
 * Read the stored device token.
 *
 * @returns The device token, or null when this phone is not yet registered.
 */
export async function getDeviceToken(): Promise<string | null> {
  return SecureStore.getItemAsync(SECURE_STORE_DEVICE_TOKEN);
}

/**
 * Read the stored device UUID.
 *
 * @returns The device UUID, or null when unavailable.
 */
export async function getDeviceId(): Promise<string | null> {
  return SecureStore.getItemAsync(SECURE_STORE_DEVICE_ID);
}

/**
 * Register this phone with the backend if it is not already registered.
 *
 * Idempotent: returns the cached token when one is already stored.
 *
 * @returns The device token to send in the X-Device-Token header.
 * @throws Error when registration fails and no token is cached.
 */
export async function ensureDeviceRegistered(): Promise<string> {
  const existing = await getDeviceToken();
  if (existing) {
    return existing;
  }

  const result = (await apiRequest("/devices/register", {
    method: "POST",
    body: JSON.stringify({ type: MOBILE_DEVICE_TYPE }),
  })) as DeviceRegisterResponse;

  await SecureStore.setItemAsync(SECURE_STORE_DEVICE_TOKEN, result.device_token);
  await SecureStore.setItemAsync(SECURE_STORE_DEVICE_ID, result.device_id);
  await storeDeviceKey(result.encryption_key_b64);

  return result.device_token;
}

/**
 * Clear every device-scoped secret.
 *
 * Called when the backend revokes the device (401 on sync) or on logout, so a
 * revoked phone cannot keep matching against a stale hotlist.
 *
 * @returns Resolves once all device state has been removed.
 */
export async function clearDevice(): Promise<void> {
  clearHotlist();
  await clearDeviceKey();
  await SecureStore.deleteItemAsync(SECURE_STORE_DEVICE_TOKEN);
  await SecureStore.deleteItemAsync(SECURE_STORE_DEVICE_ID);
}
