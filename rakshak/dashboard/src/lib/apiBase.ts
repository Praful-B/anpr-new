/**
 * @module apiBase
 * Resolves the REST and WebSocket base URLs used by the dashboard.
 *
 * Both are derived from the single `VITE_API_URL` variable so the same build
 * works behind the nginx reverse proxy (relative path) and against a directly
 * reachable backend (absolute URL). No host is hardcoded: when the value is
 * relative it is resolved against the current page origin, when it is absolute
 * the scheme is switched from http(s) to ws(s).
 */

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** Relative API prefix used when `VITE_API_URL` is not configured. */
const DEFAULT_API_BASE_URL = "/api/v1";

/** Backend path of the dashboard real-time channel. */
const DASHBOARD_WS_PATH = "/ws/dashboard";

/** TLS scheme used by absolute backend URLs. */
const HTTPS_PROTOCOL = "https:";

/** Secure WebSocket scheme. */
const WSS_PROTOCOL = "wss:";

/** Insecure WebSocket scheme. */
const WS_PROTOCOL = "ws:";

// ---------------------------------------------------------------------------
// Resolution
// ---------------------------------------------------------------------------

/**
 * Build the absolute WebSocket URL for the dashboard channel.
 *
 * @returns A `ws://` or `wss://` URL pointing at `/ws/dashboard`, resolved
 *          against the page origin when `VITE_API_URL` is relative.
 */
function buildDashboardWsUrl(): string {
  const url = new URL(API_BASE_URL, window.location.origin);
  url.protocol = url.protocol === HTTPS_PROTOCOL ? WSS_PROTOCOL : WS_PROTOCOL;
  url.pathname = DASHBOARD_WS_PATH;
  url.search = "";
  return url.toString();
}

/** Base URL for REST requests — `VITE_API_URL`, or a relative proxied path. */
export const API_BASE_URL: string = import.meta.env.VITE_API_URL || DEFAULT_API_BASE_URL;

/** Absolute WebSocket URL for the dashboard real-time channel. */
export const WS_BASE_URL: string = buildDashboardWsUrl();
