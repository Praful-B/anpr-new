/**
 * @module PolicePlaceholder
 * Placeholder page for the police dashboard — will be fully implemented in Step 8.
 */

import React from "react";

/**
 * Renders a placeholder for the police dashboard route.
 */
export default function PolicePlaceholder(): React.JSX.Element {
  return (
    <div className="flex min-h-screen items-center justify-center bg-gray-50">
      <div className="text-center">
        <h1 className="text-3xl font-bold text-gray-900">Police Dashboard</h1>
        <p className="mt-4 text-lg text-gray-600">
          Coming in Step 8 — hotlist table, vehicle detail, map, FIR verify.
        </p>
      </div>
    </div>
  );
}
