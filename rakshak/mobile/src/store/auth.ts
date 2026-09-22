/**
 * @module auth-store
 * Simple in-memory auth state management for the mobile app.
 *
 * Holds the current user's access token, decoded payload, and role.
 * Tokens are persisted via expo-secure-store (refresh) and in-memory (access).
 */

import * as SecureStore from "expo-secure-store";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** SecureStore key for the JWT access token (in-memory only, but persisted here for session restore). */
const SECURE_STORE_ACCESS_KEY = "rakshak_access_token";

/** SecureStore key for the JWT refresh token. */
const SECURE_STORE_REFRESH_KEY = "rakshak_refresh_token";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** User roles matching the backend Role enum. */
export type Role = "CITIZEN" | "VOLUNTEER" | "COP" | "ADMIN";

/** Decoded JWT payload (subset used by the app). */
export interface TokenPayload {
  sub: string;
  role: Role;
  exp: number;
  type: "access" | "refresh";
}

/** Auth state change listener. */
type AuthListener = () => void;

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

let _accessToken: string | null = null;
let _user: TokenPayload | null = null;
const _listeners: AuthListener[] = [];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Decode a JWT payload without verifying the signature.
 *
 * @param token - Encoded JWT string.
 * @returns Decoded payload, or null if decoding fails.
 */
function decodeJwtPayload(token: string): TokenPayload | null {
  try {
    const base64Url = token.split(".")[1];
    if (!base64Url) return null;
    const base64 = base64Url.replace(/-/g, "+").replace(/_/g, "/");
    const jsonPayload = decodeURIComponent(
      atob(base64)
        .split("")
        .map((c) => `%${c.charCodeAt(0).toString(16).padStart(2, "0")}`)
        .join("")
    );
    return JSON.parse(jsonPayload) as TokenPayload;
  } catch {
    return null;
  }
}

/**
 * Notify all registered listeners of an auth state change.
 */
function notifyListeners(): void {
  for (const listener of _listeners) {
    listener();
  }
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Get the current user's decoded token payload.
 *
 * @returns TokenPayload if authenticated, null otherwise.
 */
export function getCurrentUser(): TokenPayload | null {
  return _user;
}

/**
 * Check if a user is currently authenticated.
 *
 * @returns True if access token exists and is not expired.
 */
export function isAuthenticated(): boolean {
  if (!_user || !_accessToken) return false;
  return _user.exp * 1000 > Date.now();
}

/**
 * Get the current access token.
 *
 * @returns The access token string, or null.
 */
export function getAccessToken(): string | null {
  return _accessToken;
}

/**
 * Set tokens after a successful login. Persists refresh in SecureStore.
 *
 * @param accessToken  - JWT access token.
 * @param refreshToken - JWT refresh token.
 */
export async function setTokens(
  accessToken: string,
  refreshToken: string
): Promise<void> {
  _accessToken = accessToken;
  _user = decodeJwtPayload(accessToken);
  await SecureStore.setItemAsync(SECURE_STORE_ACCESS_KEY, accessToken);
  await SecureStore.setItemAsync(SECURE_STORE_REFRESH_KEY, refreshToken);
  notifyListeners();
}

/**
 * Restore tokens from SecureStore on app start.
 *
 * @returns True if tokens were restored and are still valid.
 */
export async function restoreTokens(): Promise<boolean> {
  const accessToken = await SecureStore.getItemAsync(SECURE_STORE_ACCESS_KEY);
  if (!accessToken) return false;

  const payload = decodeJwtPayload(accessToken);
  if (!payload || payload.exp * 1000 <= Date.now()) {
    await clearTokens();
    return false;
  }

  _accessToken = accessToken;
  _user = payload;
  notifyListeners();
  return true;
}

/**
 * Get the stored refresh token from SecureStore.
 *
 * @returns The refresh token, or null.
 */
export async function getRefreshToken(): Promise<string | null> {
  return SecureStore.getItemAsync(SECURE_STORE_REFRESH_KEY);
}

/**
 * Clear all tokens and user state (on logout or 401).
 */
export async function clearTokens(): Promise<void> {
  _accessToken = null;
  _user = null;
  await SecureStore.deleteItemAsync(SECURE_STORE_ACCESS_KEY);
  await SecureStore.deleteItemAsync(SECURE_STORE_REFRESH_KEY);
  notifyListeners();
}

/**
 * Register a listener for auth state changes.
 *
 * @param listener - Function to call on auth state change.
 * @returns Unsubscribe function.
 */
export function onAuthChange(listener: AuthListener): () => void {
  _listeners.push(listener);
  return () => {
    const idx = _listeners.indexOf(listener);
    if (idx >= 0) _listeners.splice(idx, 1);
  };
}
