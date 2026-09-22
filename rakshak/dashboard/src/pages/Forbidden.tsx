/**
 * @module Forbidden
 * 403 page — displayed when a user lacks the required role to access
 * a protected route.
 */

import React from "react";
import { Link } from "react-router-dom";

/**
 * Renders a 403 Forbidden page with a message and link back to login.
 */
export default function Forbidden(): React.JSX.Element {
  return (
    <div className="flex min-h-screen items-center justify-center bg-gray-50">
      <div className="text-center">
        <h1 className="text-6xl font-bold text-red-600">403</h1>
        <p className="mt-4 text-lg text-gray-700">
          You do not have permission to access this page.
        </p>
        <p className="mt-2 text-sm text-gray-500">
          Please sign in with an authorized account.
        </p>
        <Link
          to="/login"
          className="mt-6 inline-block rounded-md bg-indigo-600 px-4 py-2 text-white hover:bg-indigo-700"
        >
          Sign In
        </Link>
      </div>
    </div>
  );
}
