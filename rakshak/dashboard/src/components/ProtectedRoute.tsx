/**
 * @module ProtectedRoute
 * Route guard that redirects unauthenticated users to /login
 * and shows a 403 page when the user's role does not match.
 */

import React from "react";
import { Navigate, Outlet } from "react-router-dom";
import { useAuth, type Role } from "../lib/auth";

interface ProtectedRouteProps {
  /** Allowed roles. If empty, any authenticated user may access. */
  allowedRoles?: Role[];
}

/**
 * Wrapper around an Outlet that enforces authentication and optional
 * role-based access control.
 *
 * @param props         - Configuration including allowed roles.
 * @returns The child route or a redirect.
 */
export default function ProtectedRoute({
  allowedRoles = [],
}: ProtectedRouteProps): React.JSX.Element {
  const { isAuthenticated, user } = useAuth();

  if (!isAuthenticated || !user) {
    return <Navigate to="/login" replace />;
  }

  if (allowedRoles.length > 0 && !allowedRoles.includes(user.role)) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-gray-50">
        <div className="text-center">
          <h1 className="text-6xl font-bold text-red-600">403</h1>
          <p className="mt-4 text-lg text-gray-700">
            You do not have permission to access this page.
          </p>
          <p className="mt-2 text-sm text-gray-500">
            Required role: {allowedRoles.join(" or ")} &middot; Your role: {user.role}
          </p>
        </div>
      </div>
    );
  }

  return <Outlet />;
}
