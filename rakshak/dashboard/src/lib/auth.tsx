/**
 * @module auth
 * Authentication context and token management for the RAKSHAK dashboard.
 *
 * Access tokens are held in-memory only (never localStorage/sessionStorage).
 * Refresh tokens live in an HttpOnly cookie set by the backend.
 */

import React, { createContext, useCallback, useContext, useMemo, useState } from "react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** Roles matching the backend Role enum. */
export type Role = "CITIZEN" | "VOLUNTEER" | "COP" | "ADMIN";

/** Decoded JWT payload (subset used by the dashboard). */
interface TokenPayload {
  sub: string;
  role: Role;
  exp: number;
  type: "access" | "refresh";
}

/** Shape of the authentication context exposed via useAuth(). */
export interface AuthContextValue {
  /** Current access token (in-memory only). */
  accessToken: string | null;
  /** Decoded claims from the current access token. */
  user: TokenPayload | null;
  /** Whether the access token is present and unexpired. */
  isAuthenticated: boolean;
  /** Persist tokens in memory after a successful login. */
  setTokens: (accessToken: string, refreshToken: string) => void;
  /** Clear all in-memory tokens. */
  logout: () => void;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** In-memory access token storage. */
let _accessToken: string | null = null;

/** In-memory refresh token (mirror of HttpOnly cookie value for refresh). */
let _refreshToken: string | null = null;

// ---------------------------------------------------------------------------
// Public helpers (used by api.ts and auth flow)
// ---------------------------------------------------------------------------

/**
 * Retrieve the current in-memory access token.
 *
 * @returns The access token string, or null.
 */
export function getAccessToken(): string | null {
  return _accessToken;
}

/**
 * Retrieve the current in-memory refresh token.
 *
 * @returns The refresh token string, or null.
 */
export function getRefreshToken(): string | null {
  return _refreshToken;
}

/**
 * Store both access and refresh tokens in memory.
 *
 * @param accessToken  - Short-lived JWT access token.
 * @param refreshToken - Long-lived JWT refresh token (also set as HttpOnly cookie by backend).
 */
export function setTokens(accessToken: string, refreshToken: string): void {
  _accessToken = accessToken;
  _refreshToken = refreshToken;
}

/**
 * Clear all in-memory tokens (on logout or 401 expiry).
 */
export function clearTokens(): void {
  _accessToken = null;
  _refreshToken = null;
}

/**
 * Decode the payload portion of a JWT without verifying the signature.
 *
 * @param token - Encoded JWT string.
 * @returns Decoded payload object, or null if decoding fails.
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
        .join(""),
    );
    return JSON.parse(jsonPayload) as TokenPayload;
  } catch {
    return null;
  }
}

// ---------------------------------------------------------------------------
// Context
// ---------------------------------------------------------------------------

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

// ---------------------------------------------------------------------------
// Provider
// ---------------------------------------------------------------------------

interface AuthProviderProps {
  children: React.ReactNode;
}

/**
 * Authentication provider that manages token state and exposes the
 * {@link AuthContextValue} to the component tree.
 *
 * @param props - React props, expects `children`.
 */
export function AuthProvider({ children }: AuthProviderProps): React.JSX.Element {
  const [token, setToken] = useState<string | null>(_accessToken);

  const user = useMemo<TokenPayload | null>(() => {
    if (!token) return null;
    const payload = decodeJwtPayload(token);
    if (!payload) return null;
    // Check expiry
    if (payload.exp * 1000 < Date.now()) return null;
    return payload;
  }, [token]);

  const isAuthenticated = user !== null && user.type === "access";

  const storeTokens = useCallback((accessToken: string, refreshToken: string) => {
    setTokens(accessToken, refreshToken);
    setToken(accessToken);
  }, []);

  const logout = useCallback(() => {
    clearTokens();
    setToken(null);
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      accessToken: token,
      user,
      isAuthenticated,
      setTokens: storeTokens,
      logout,
    }),
    [token, user, isAuthenticated, storeTokens, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

/**
 * Hook to access the current authentication context.
 *
 * Must be used within an {@link AuthProvider} ancestor.
 *
 * @returns The current {@link AuthContextValue}.
 * @throws If used outside of an AuthProvider.
 */
export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return ctx;
}
