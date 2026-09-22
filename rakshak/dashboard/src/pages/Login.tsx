/**
 * @module Login
 * Login page — email/password form that authenticates against
 * POST /api/v1/auth/login, stores the tokens in memory, and
 * redirects to /citizen by default.
 */

import React, { useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { apiRequest, ApiError } from "../lib/api";
import { useAuth } from "../lib/auth";

interface LoginResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

const REDIRECT_PATHS: Record<string, string> = {
  CITIZEN: "/citizen",
  VOLUNTEER: "/citizen",
  COP: "/police",
  ADMIN: "/admin",
};

/**
 * Renders a login form, submits credentials, and navigates on success.
 */
export default function Login(): React.JSX.Element {
  const { setTokens } = useAuth();
  const navigate = useNavigate();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent): Promise<void> => {
    e.preventDefault();
    setError(null);
    setLoading(true);

    try {
      const data = (await apiRequest("/auth/login", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      })) as LoginResponse;

      setTokens(data.access_token, data.refresh_token);

      // Decode the access token to determine role-based redirect.
      const base64Url = data.access_token.split(".")[1];
      const base64 = base64Url.replace(/-/g, "+").replace(/_/g, "/");
      const payload = JSON.parse(
        decodeURIComponent(
          atob(base64)
            .split("")
            .map((c) => `%${c.charCodeAt(0).toString(16).padStart(2, "0")}`)
            .join(""),
        ),
      ) as { role: string };

      navigate(REDIRECT_PATHS[payload.role] ?? "/citizen", { replace: true });
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message);
      } else {
        setError("An unexpected error occurred. Please try again.");
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-gray-50 px-4">
      <div className="w-full max-w-md rounded-lg bg-white p-8 shadow">
        <h1 className="mb-6 text-center text-2xl font-bold text-gray-900">
          Sign in to RAKSHAK
        </h1>

        {error && (
          <div className="mb-4 rounded-md bg-red-50 p-3 text-sm text-red-700">
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label htmlFor="email" className="block text-sm font-medium text-gray-700">
              Email
            </label>
            <input
              id="email"
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 shadow-sm focus:border-indigo-500 focus:outline-none focus:ring-indigo-500"
            />
          </div>

          <div>
            <label htmlFor="password" className="block text-sm font-medium text-gray-700">
              Password
            </label>
            <input
              id="password"
              type="password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 shadow-sm focus:border-indigo-500 focus:outline-none focus:ring-indigo-500"
            />
          </div>

          <button
            type="submit"
            disabled={loading}
            className="w-full rounded-md bg-indigo-600 px-4 py-2 text-white font-medium hover:bg-indigo-700 disabled:opacity-50"
          >
            {loading ? "Signing in..." : "Sign In"}
          </button>
        </form>

        <p className="mt-4 text-center text-sm text-gray-600">
          Don&apos;t have an account?{" "}
          <Link to="/register" className="text-indigo-600 hover:underline">
            Register
          </Link>
        </p>
      </div>
    </div>
  );
}
