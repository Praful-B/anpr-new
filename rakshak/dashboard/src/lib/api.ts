/**
 * @module api
 * Centralized fetch wrapper for the RAKSHAK API.
 *
 * Uses the shared API base URL from `@/lib/apiBase`, attaches the in-memory
 * access token via the Authorization header, and transparently attempts a
 * single refresh cycle on 401 responses before giving up.
 */

import { getAccessToken, getRefreshToken, setTokens, clearTokens } from "./auth";
import { API_BASE_URL } from "./apiBase";

/** Maximum number of retry attempts after a 401 response. */
const MAX_RETRY_ATTEMPTS = 1;

interface ApiErrorBody {
  detail?: string;
}

export class ApiError extends Error {
  /** HTTP status code from the failed response. */
  public readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

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
  token?: string,
): Promise<unknown> {
  const headers: Record<string, string> = {
    ...(options.headers as Record<string, string> | undefined),
  };

  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  // Only set Content-Type to JSON when the body is a plain string/object
  // (not FormData, which needs its own boundary).
  if (options.body && !(options.body instanceof FormData)) {
    if (!headers["Content-Type"]) {
      headers["Content-Type"] = "application/json";
    }
  }

  const response = await fetch(`${API_BASE_URL}${endpoint}`, {
    ...options,
    headers,
    credentials: "include", // send cookies (HttpOnly refresh token)
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

  // 204 No Content
  if (response.status === 204) {
    return null;
  }

  return response.json();
}

/**
 * Attempt to refresh the access + refresh tokens using the HttpOnly cookie.
 *
 * @returns The newly issued access token, or null if refresh failed.
 */
async function attemptRefresh(): Promise<string | null> {
  try {
    const refreshToken = getRefreshToken();
    if (!refreshToken) return null;

    const result = await executeRequest("/auth/refresh", {
      method: "POST",
      body: JSON.stringify({ refresh_token: refreshToken }),
    });

    const data = result as { access_token: string; refresh_token: string };
    setTokens(data.access_token, data.refresh_token);
    return data.access_token;
  } catch {
    clearTokens();
    return null;
  }
}

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
  options: RequestInit = {},
): Promise<unknown> {
  let token = getAccessToken();

  try {
    return await executeRequest(endpoint, options, token ?? undefined);
  } catch (err) {
    if (err instanceof ApiError && err.status === 401 && MAX_RETRY_ATTEMPTS > 0) {
      const newToken = await attemptRefresh();
      if (newToken) {
        return executeRequest(endpoint, options, newToken);
      }
    }
    throw err;
  }
}
