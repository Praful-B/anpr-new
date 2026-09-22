/**
 * @module AnalyticsPlaceholder
 * Placeholder page for the analytics dashboard — will be fully implemented in Step 9.
 */

import React from "react";

/**
 * Renders a placeholder for the analytics dashboard route.
 */
export default function AnalyticsPlaceholder(): React.JSX.Element {
  return (
    <div className="flex min-h-screen items-center justify-center bg-gray-50">
      <div className="text-center">
        <h1 className="text-3xl font-bold text-gray-900">Analytics Dashboard</h1>
        <p className="mt-4 text-lg text-gray-600">
          Coming in Step 9 — heatmap, recovery metrics, device coverage.
        </p>
      </div>
    </div>
  );
}
