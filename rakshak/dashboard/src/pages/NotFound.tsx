/**
 * @module NotFound
 * 404 page — displayed when no route matches.
 */

import React from "react";
import { Link } from "react-router-dom";

/**
 * Renders a simple 404 page with a link back to the dashboard root.
 */
export default function NotFound(): React.JSX.Element {
  return (
    <div className="flex min-h-screen items-center justify-center bg-gray-50">
      <div className="text-center">
        <h1 className="text-6xl font-bold text-gray-900">404</h1>
        <p className="mt-4 text-lg text-gray-700">Page not found</p>
        <Link
          to="/"
          className="mt-6 inline-block rounded-md bg-indigo-600 px-4 py-2 text-white hover:bg-indigo-700"
        >
          Go Home
        </Link>
      </div>
    </div>
  );
}
