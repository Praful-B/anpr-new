/**
 * @module PoliceHotlist
 * Hotlist table page — displays all hot-listed vehicles in a paginated
 * table with filters for status, plate, and date range. Subscribes
 * to WebSocket new_sighting events for real-time row updates.
 */

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { apiRequest, ApiError } from "../lib/api";
import { wsClient, type WsMessage } from "../lib/ws";
// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** Valid hotlist statuses for the filter dropdown. */
const STATUS_OPTIONS: readonly string[] = [
  "",
  "PENDING_VERIFICATION",
  "ACTIVE_UNCONFIRMED",
  "ACTIVE_CONFIRMED",
  "EXPIRED",
  "CLOSED",
  "REJECTED",
] as const;

/** Status badge colour mapping. */
const STATUS_STYLES: Record<string, string> = {
  PENDING_VERIFICATION: "bg-yellow-100 text-yellow-800",
  ACTIVE_UNCONFIRMED: "bg-orange-100 text-orange-800",
  ACTIVE_CONFIRMED: "bg-red-100 text-red-800",
  EXPIRED: "bg-gray-100 text-gray-800",
  CLOSED: "bg-green-100 text-green-800",
  REJECTED: "bg-slate-100 text-slate-600",
};

/** Default page size for pagination. */
const DEFAULT_PAGE_SIZE = 20;

/** Highlight animation duration for new WS rows (ms). */
const HIGHLIGHT_DURATION_MS = 4000;

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** Shape of a hotlist entry returned by GET /hotlist. */
interface HotlistEntry {
  readonly id: string;
  readonly plate: string;
  readonly complaint_id: string;
  readonly status: string;
  readonly added_at: string;
  readonly fir_deadline: string | null;
  readonly fir_ref: string | null;
  readonly fir_verified_at: string | null;
  readonly cooldown_until: string | null;
  readonly recovered_at: string | null;
  readonly last_seen_at: string | null;
  readonly last_seen_lat: number | null;
  readonly last_seen_lng: number | null;
  readonly dismissed: boolean;
  readonly notes: string | null;
  readonly created_at: string;
  readonly updated_at: string;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Compute a human-readable countdown or label for the FIR deadline.
 *
 * @param deadlineIso - ISO timestamp of the deadline, or null.
 * @returns Display string for the deadline column.
 */
function formatDeadline(deadlineIso: string | null): string {
  if (!deadlineIso) return "—";
  const deadline = new Date(deadlineIso);
  const now = new Date();
  const diffMs = deadline.getTime() - now.getTime();

  if (diffMs <= 0) return "Overdue";

  const hours = Math.floor(diffMs / (1000 * 60 * 60));
  const minutes = Math.floor((diffMs % (1000 * 60 * 60)) / (1000 * 60));

  if (hours >= 24) {
    const days = Math.floor(hours / 24);
    return `${days}d ${hours % 24}h`;
  }
  return `${hours}h ${minutes}m`;
}

/**
 * Format an ISO timestamp for display.
 *
 * @param iso - ISO timestamp string.
 * @returns Formatted date string.
 */
function formatDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("en-IN", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

/**
 * Renders the police hotlist table page with filters, pagination,
 * and real-time WebSocket updates.
 */
export default function PoliceHotlist(): React.JSX.Element {
  const navigate = useNavigate();
  // --- State ---
  const [entries, setEntries] = useState<HotlistEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Filters
  const [statusFilter, setStatusFilter] = useState("");
  const [plateFilter, setPlateFilter] = useState("");
  const [fromDate, setFromDate] = useState("");
  const [toDate, setToDate] = useState("");
  const [page, setPage] = useState(1);

  // Track IDs of recently added WS entries for highlight animation
  const [highlightedIds, setHighlightedIds] = useState<Set<string>>(new Set());
  const highlightTimers = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map());

  // --- Fetch hotlist ---
  const fetchHotlist = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);

      const params = new URLSearchParams();
      params.set("page", String(page));
      params.set("per_page", String(DEFAULT_PAGE_SIZE));
      if (statusFilter) params.set("status", statusFilter);
      if (plateFilter.trim()) params.set("plate", plateFilter.trim());
      if (fromDate) params.set("from_date", new Date(fromDate).toISOString());
      if (toDate) params.set("to_date", new Date(toDate).toISOString());

      const data = (await apiRequest(`/hotlist/?${params.toString()}`)) as HotlistEntry[];
      setEntries(data);
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message);
      } else {
        setError("Failed to load hotlist.");
      }
    } finally {
      setLoading(false);
    }
  }, [page, statusFilter, plateFilter, fromDate, toDate]);

  useEffect(() => {
    fetchHotlist();
  }, [fetchHotlist]);

  // --- Reset page when filters change ---
  useEffect(() => {
    setPage(1);
  }, [statusFilter, plateFilter, fromDate, toDate]);

  // --- WebSocket subscription ---
  useEffect(() => {
    const unsubscribe = wsClient.subscribe((message: WsMessage) => {
      if (message.type === "new_sighting" && message.data) {
        const sighting = message.data as Record<string, unknown>;
        const hotlistId = sighting.hotlist_id as string | undefined;

        if (!hotlistId) return;

        // Prepend the sighting info to matching rows (update last_seen fields)
        setEntries((prev) => {
          const updated = prev.map((entry) => {
            if (entry.id === hotlistId) {
              return {
                ...entry,
                last_seen_at: (sighting.captured_at as string) ?? entry.last_seen_at,
                last_seen_lat: (sighting.lat as number) ?? entry.last_seen_lat,
                last_seen_lng: (sighting.lng as number) ?? entry.last_seen_lng,
              };
            }
            return entry;
          });
          return updated;
        });

        // Highlight the row
        if (hotlistId) {
          setHighlightedIds((prev) => new Set(prev).add(hotlistId));

          const existingTimer = highlightTimers.current.get(hotlistId);
          if (existingTimer) clearTimeout(existingTimer);

          const timer = setTimeout(() => {
            setHighlightedIds((prev) => {
              const next = new Set(prev);
              next.delete(hotlistId);
              return next;
            });
            highlightTimers.current.delete(hotlistId);
          }, HIGHLIGHT_DURATION_MS);
          highlightTimers.current.set(hotlistId, timer);
        }
      }

      if (message.type === "hotlist_change" && message.data) {
        const change = message.data as Record<string, unknown>;
        const entryId = change.id as string | undefined;

        if (entryId) {
          setEntries((prev) =>
            prev.map((entry) =>
              entry.id === entryId
                ? { ...entry, status: (change.status as string) ?? entry.status }
                : entry,
            ),
          );
        }
      }
    });

    return () => {
      unsubscribe();
      for (const timer of highlightTimers.current.values()) {
        clearTimeout(timer);
      }
    };
  }, []);

  // --- Build query params for display (memoized for filters form) ---
  const uniqueStatuses = useMemo(() => {
    return STATUS_OPTIONS;
  }, []);

  return (
    <div className="mx-auto max-w-7xl px-4 py-8">
      <h1 className="mb-6 text-2xl font-bold text-gray-900">Police Hotlist</h1>

      {/* ---------- Filters ---------- */}
      <div className="mb-6 rounded-lg bg-white p-4 shadow-sm">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <div>
            <label htmlFor="plate-filter" className="block text-sm font-medium text-gray-700">
              Plate
            </label>
            <input
              id="plate-filter"
              type="text"
              placeholder="e.g. MH12AB"
              value={plateFilter}
              onChange={(e) => setPlateFilter(e.target.value)}
              className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-indigo-500 focus:outline-none focus:ring-indigo-500"
            />
          </div>

          <div>
            <label htmlFor="status-filter" className="block text-sm font-medium text-gray-700">
              Status
            </label>
            <select
              id="status-filter"
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-indigo-500 focus:outline-none focus:ring-indigo-500"
            >
              {uniqueStatuses.map((s) => (
                <option key={s} value={s}>
                  {s ? s.replace(/_/g, " ") : "All statuses"}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label htmlFor="from-date" className="block text-sm font-medium text-gray-700">
              From
            </label>
            <input
              id="from-date"
              type="date"
              value={fromDate}
              onChange={(e) => setFromDate(e.target.value)}
              className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-indigo-500 focus:outline-none focus:ring-indigo-500"
            />
          </div>

          <div>
            <label htmlFor="to-date" className="block text-sm font-medium text-gray-700">
              To
            </label>
            <input
              id="to-date"
              type="date"
              value={toDate}
              onChange={(e) => setToDate(e.target.value)}
              className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-indigo-500 focus:outline-none focus:ring-indigo-500"
            />
          </div>
        </div>
      </div>

      {/* ---------- Error ---------- */}
      {error && (
        <div className="mb-4 rounded-md bg-red-50 p-3 text-sm text-red-700">{error}</div>
      )}

      {/* ---------- Table ---------- */}
      <div className="overflow-hidden rounded-lg bg-white shadow-sm">
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                  Plate
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                  Status
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                  Added
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                  FIR Deadline
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                  Last Seen
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200 bg-white">
              {loading && (
                <tr>
                  <td colSpan={6} className="px-6 py-8 text-center text-sm text-gray-500">
                    Loading...
                  </td>
                </tr>
              )}

              {!loading && entries.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-6 py-8 text-center text-sm text-gray-500">
                    No hotlist entries found.
                  </td>
                </tr>
              )}

              {!loading &&
                entries.map((entry) => {
                  const isHighlighted = highlightedIds.has(entry.id);
                  return (
                    <tr
                      key={entry.id}
                      onClick={() => navigate(`/police/vehicle/${entry.id}`)}
                      className={`cursor-pointer transition-colors duration-500 hover:bg-gray-50 ${
                        isHighlighted ? "bg-blue-50" : ""
                      }`}
                    >
                      <td className="whitespace-nowrap px-6 py-4">
                        <span className="font-mono text-sm font-bold text-gray-900">
                          {entry.plate}
                        </span>
                      </td>
                      <td className="whitespace-nowrap px-6 py-4">
                        <span
                          className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-medium ${
                            STATUS_STYLES[entry.status] ?? "bg-gray-100 text-gray-800"
                          }`}
                        >
                          {entry.status.replace(/_/g, " ")}
                        </span>
                      </td>
                      <td className="whitespace-nowrap px-6 py-4 text-sm text-gray-600">
                        {formatDate(entry.added_at)}
                      </td>
                      <td className="whitespace-nowrap px-6 py-4 text-sm">
                        <span
                          className={
                            entry.fir_deadline && new Date(entry.fir_deadline) < new Date()
                              ? "font-medium text-red-600"
                              : "text-gray-600"
                          }
                        >
                          {formatDeadline(entry.fir_deadline)}
                        </span>
                      </td>
                      <td className="whitespace-nowrap px-6 py-4 text-sm text-gray-600">
                        {formatDate(entry.last_seen_at)}
                      </td>
                      <td className="whitespace-nowrap px-6 py-4 text-sm">
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            navigate(`/police/vehicle/${entry.id}`);
                          }}
                          className="text-indigo-600 hover:text-indigo-800"
                        >
                          View
                        </button>
                      </td>
                    </tr>
                  );
                })}
            </tbody>
          </table>
        </div>
      </div>

      {/* ---------- Pagination ---------- */}
      <div className="mt-4 flex items-center justify-between">
        <button
          onClick={() => setPage((p) => Math.max(1, p - 1))}
          disabled={page <= 1}
          className="rounded-md border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
        >
          Previous
        </button>
        <span className="text-sm text-gray-700">Page {page}</span>
        <button
          onClick={() => setPage((p) => p + 1)}
          disabled={entries.length < DEFAULT_PAGE_SIZE}
          className="rounded-md border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
        >
          Next
        </button>
      </div>
    </div>
  );
}
