/**
 * @module api
 * Centralized fetch wrapper for the RAKSHAK mobile API.
 *
 * Mirrors the dashboard's lib/api.ts contract: in-memory access token,
 * expo-secure-store for refresh token, automatic single-retry on 401.
 * The base URL comes from the EXPO_PUBLIC_API_URL environment variable
 * (see mobile/.env.example); nothing is hardcoded.
 */

import * as SecureStore from "expo-secure-store";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** Environment variable holding the backend base URL for this build. */
const API_URL_ENV_VAR = "EXPO_PUBLIC_API_URL";

/**
 * Resolve the backend base URL for this build.
 *
 * @returns The configured API base URL.
 * @throws Error when EXPO_PUBLIC_API_URL is not set, so a misconfigured build
 *         fails immediately instead of silently pointing at the wrong host.
 */
function resolveBaseUrl(): string {
  const configured = process.env[API_URL_ENV_VAR];
  if (!configured) {
    throw new Error(
      `${API_URL_ENV_VAR} is not set. Copy mobile/.env.example to mobile/.env and restart Expo.`
    );
  }
  return configured;
}

/** SecureStore keys for persistent token storage. */
const SECURE_STORE_REFRESH_KEY = "rakshak_refresh_token";

/** Maximum number of retry attempts after a 401 response. */
const MAX_RETRY_ATTEMPTS = 1;

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** Custom error class for API failures with HTTP status. */
export class ApiError extends Error {
  /** HTTP status code from the failed response. */
  public readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

/** Response body shape when the server returns an error detail. */
interface ApiErrorBody {
  detail?: string;
}

// ---------------------------------------------------------------------------
// In-memory access token
// ---------------------------------------------------------------------------

/** Base URL for every request issued by this module. */
const BASE_URL: string = resolveBaseUrl();

let _accessToken: string | null = null;

/**
 * Retrieve the current in-memory access token.
 *
 * @returns The access token string, or null if not set.
 */
export function getAccessToken(): string | null {
  return _accessToken;
}

/**
 * Set the in-memory access token.
 *
 * @param token - JWT access token to store.
 */
export function setAccessToken(token: string): void {
  _accessToken = token;
}

/**
 * Clear the in-memory access token.
 */
export function clearAccessToken(): void {
  _accessToken = null;
}

// ---------------------------------------------------------------------------
// Refresh token (expo-secure-store)
// ---------------------------------------------------------------------------

/**
 * Retrieve the refresh token from expo-secure-store.
 *
 * @returns The refresh token string, or null if not stored.
 */
export async function getRefreshToken(): Promise<string | null> {
  return SecureStore.getItemAsync(SECURE_STORE_REFRESH_KEY);
}

/**
 * Persist the refresh token in expo-secure-store.
 *
 * @param token - The refresh token to store.
 */
export async function setRefreshToken(token: string): Promise<void> {
  await SecureStore.setItemAsync(SECURE_STORE_REFRESH_KEY, token);
}

/**
 * Remove the refresh token from expo-secure-store.
 */
export async function clearRefreshToken(): Promise<void> {
  await SecureStore.deleteItemAsync(SECURE_STORE_REFRESH_KEY);
}

// ---------------------------------------------------------------------------
// Request execution
// ---------------------------------------------------------------------------

/**
 * Execute a single fetch call with optional Authorization header.
 *
 * @param endpoint - Path relative to the API base URL (e.g. `/auth/login`).
 * @param options  - Standard RequestInit options (body, method, headers).
 * @param token    - Optional access token to attach as Bearer.
 * @returns Parsed JSON response body.
 * @throws ApiError on non-2xx responses.
 */
async function executeRequest(
  endpoint: string,
  options: RequestInit = {},
  token?: string
): Promise<unknown> {
  const headers: Record<string, string> = {
    ...(options.headers as Record<string, string> | undefined),
  };

  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  if (options.body && !(options.body instanceof FormData)) {
    if (!headers["Content-Type"]) {
      headers["Content-Type"] = "application/json";
    }
  }

  const response = await fetch(`${BASE_URL}${endpoint}`, {
    ...options,
    headers,
  });

  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const body: ApiErrorBody = await response.json();
      if (body.detail) detail = body.detail;
    } catch {
      // Response body was not JSON; use status code as message.
    }
    throw new ApiError(response.status, detail);
  }

  if (response.status === 204) {
    return null;
  }

  return response.json();
}

// ---------------------------------------------------------------------------
// Token refresh
// ---------------------------------------------------------------------------

/**
 * Attempt to refresh the access + refresh tokens using stored refresh token.
 *
 * @returns The newly issued access token, or null if refresh failed.
 */
async function attemptRefresh(): Promise<string | null> {
  try {
    const refreshToken = await getRefreshToken();
    if (!refreshToken) return null;

    const result = await executeRequest("/auth/refresh", {
      method: "POST",
      body: JSON.stringify({ refresh_token: refreshToken }),
    });

    const data = result as { access_token: string; refresh_token: string };
    setAccessToken(data.access_token);
    await setRefreshToken(data.refresh_token);
    return data.access_token;
  } catch {
    clearAccessToken();
    await clearRefreshToken();
    return null;
  }
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Make an authenticated API request with automatic token refresh on 401.
 *
 * @param endpoint - API path (e.g. `/complaints/mine`).
 * @param options  - Standard RequestInit options.
 * @returns Parsed JSON response body.
 * @throws ApiError on unrecoverable HTTP errors.
 */
export async function apiRequest(
  endpoint: string,
  options: RequestInit = {}
): Promise<unknown> {
  let token = getAccessToken();

  try {
    return await executeRequest(endpoint, options, token ?? undefined);
  } catch (err) {
    if (
      err instanceof ApiError &&
      err.status === 401 &&
      MAX_RETRY_ATTEMPTS > 0
    ) {
      const newToken = await attemptRefresh();
      if (newToken) {
        return executeRequest(endpoint, options, newToken);
      }
    }
    throw err;
  }
}

/**
 * Make an API request with a device token (X-Device-Token header).
 *
 * @param endpoint   - API path (e.g. `/sightings`).
 * @param deviceToken - The device authentication token.
 * @param options    - Standard RequestInit options.
 * @returns Parsed JSON response body.
 * @throws ApiError on non-2xx responses.
 */
export async function deviceApiRequest(
  endpoint: string,
  deviceToken: string,
  options: RequestInit = {}
): Promise<unknown> {
  const headers: Record<string, string> = {
    ...(options.headers as Record<string, string> | undefined),
    "X-Device-Token": deviceToken,
  };

  if (options.body && !(options.body instanceof FormData)) {
    if (!headers["Content-Type"]) {
      headers["Content-Type"] = "application/json";
    }
  }

  const response = await fetch(`${BASE_URL}${endpoint}`, {
    ...options,
    headers,
  });

  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const body: ApiErrorBody = await response.json();
      if (body.detail) detail = body.detail;
    } catch {
      // Response body was not JSON.
    }
    throw new ApiError(response.status, detail);
  }

  if (response.status === 204) {
    return null;
  }

  return response.json();
}
