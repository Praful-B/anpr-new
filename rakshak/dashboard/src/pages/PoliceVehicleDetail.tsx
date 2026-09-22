/**
 * @module PoliceVehicleDetail
 * Vehicle detail page — shows a single hotlist entry with complaint info,
 * a Leaflet map plotting the last 50 sightings as a polyline trail,
 * a sighting list, and action buttons (verify FIR, mark recovered,
 * dismiss, remove).
 */

import React, { useCallback, useEffect, useRef, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { apiRequest, ApiError } from "../lib/api";
import { wsClient, type WsMessage } from "../lib/ws";
import { useToast } from "../components/Toast";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** Status badge colour mapping. */
const STATUS_STYLES: Record<string, string> = {
  PENDING_VERIFICATION: "bg-yellow-100 text-yellow-800",
  ACTIVE_UNCONFIRMED: "bg-orange-100 text-orange-800",
  ACTIVE_CONFIRMED: "bg-red-100 text-red-800",
  EXPIRED: "bg-gray-100 text-gray-800",
  CLOSED: "bg-green-100 text-green-800",
  REJECTED: "bg-slate-100 text-slate-600",
};

/** Default map centre (New Delhi) when no sightings exist. */
const DEFAULT_MAP_LAT = 28.6139;

/** Default map centre longitude. */
const DEFAULT_MAP_LNG = 77.2090;

/** Default zoom level when no sightings exist. */
const DEFAULT_MAP_ZOOM = 5;

/** Zoom level when sightings exist. */
const SIGHTING_MAP_ZOOM = 13;

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** Shape of the hotlist detail response from GET /hotlist/{id}. */
interface HotlistDetail {
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
  readonly complaint: ComplaintInfo | null;
  readonly sightings: SightingInfo[];
}

/** Shape of the nested complaint object. */
interface ComplaintInfo {
  readonly id: string;
  readonly user_id: string;
  readonly plate: string;
  readonly proof_ref: string | null;
  readonly status: string;
  readonly rejection_reason: string | null;
  readonly created_at: string;
  readonly updated_at: string;
}

/** Shape of a sighting in the detail response. */
interface SightingInfo {
  readonly id: string;
  readonly lat: number;
  readonly lng: number;
  readonly captured_at: string;
  readonly confidence: number;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

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
// Sub-components
// ---------------------------------------------------------------------------

interface LeafletMapProps {
  sightings: readonly SightingInfo[];
}

/**
 * Renders a Leaflet map with sighting markers and a polyline trail.
 *
 * @param props - The list of sightings to plot.
 */
function LeafletMap({ sightings }: LeafletMapProps): React.JSX.Element {
  const mapRef = useRef<HTMLDivElement>(null);
  const mapInstanceRef = useRef<unknown>(null);

  useEffect(() => {
    if (!mapRef.current) return;

    let cancelled = false;

    const initMap = async (): Promise<void> => {
      const L = await import("leaflet");

      if (cancelled || !mapRef.current) return;

      if (mapInstanceRef.current) {
        (mapInstanceRef.current as { remove: () => void }).remove();
      }

      const hasSightings = sightings.length > 0;
      const centerLat = hasSightings ? sightings[sightings.length - 1].lat : DEFAULT_MAP_LAT;
      const centerLng = hasSightings ? sightings[sightings.length - 1].lng : DEFAULT_MAP_LNG;
      const zoom = hasSightings ? SIGHTING_MAP_ZOOM : DEFAULT_MAP_ZOOM;

      const map = L.map(mapRef.current).setView([centerLat, centerLng], zoom);

      L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
      }).addTo(map);

      if (hasSightings) {
        const latLngs: L.LatLngExpression[] = sightings.map((s) => [s.lat, s.lng]);

        L.polyline(latLngs, { color: "#6366f1", weight: 3, opacity: 0.7 }).addTo(map);

        sightings.forEach((sighting, index) => {
          const marker = L.circleMarker([sighting.lat, sighting.lng], {
            radius: 6,
            fillColor: index === sightings.length - 1 ? "#ef4444" : "#6366f1",
            color: "#fff",
            weight: 2,
            fillOpacity: 0.9,
          }).addTo(map);

          const timestamp = formatDate(sighting.captured_at);
          marker.bindPopup(
            `<div style="font-size:12px">
              <strong>#${index + 1}</strong><br/>
              ${timestamp}<br/>
              Confidence: ${sighting.confidence}%
            </div>`,
          );
        });

        map.fitBounds(L.latLngBounds(latLngs).pad(0.1));
      }

      mapInstanceRef.current = map;
    };

    void initMap();

    return () => {
      cancelled = true;
      if (mapInstanceRef.current) {
        (mapInstanceRef.current as { remove: () => void }).remove();
        mapInstanceRef.current = null;
      }
    };
  }, [sightings]);

  return (
    <div
      ref={mapRef}
      className="h-96 w-full rounded-lg border border-gray-200"
      aria-label="Sighting map"
    />
  );
}

interface FirVerifyModalProps {
  isOpen: boolean;
  onClose: () => void;
  onVerify: (firRef: string) => Promise<void>;
  loading: boolean;
  error: string | null;
}

/**
 * Modal dialog for entering an FIR reference number.
 *
 * @param props - Modal state and callbacks.
 */
function FirVerifyModal({
  isOpen,
  onClose,
  onVerify,
  loading,
  error,
}: FirVerifyModalProps): React.JSX.Element | null {
  const [firRef, setFirRef] = useState("");

  if (!isOpen) return null;

  const handleSubmit = async (e: React.FormEvent): Promise<void> => {
    e.preventDefault();
    if (firRef.trim()) {
      await onVerify(firRef.trim());
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black bg-opacity-50">
      <div className="mx-4 w-full max-w-md rounded-lg bg-white p-6 shadow-xl">
        <h2 className="mb-4 text-lg font-bold text-gray-900">Verify FIR</h2>

        {error && (
          <div className="mb-4 rounded-md bg-red-50 p-3 text-sm text-red-700">{error}</div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label htmlFor="fir-ref" className="block text-sm font-medium text-gray-700">
              FIR Reference Number
            </label>
            <input
              id="fir-ref"
              type="text"
              required
              maxLength={100}
              placeholder="e.g. FIR/2026/12345"
              value={firRef}
              onChange={(e) => setFirRef(e.target.value)}
              className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 shadow-sm focus:border-indigo-500 focus:outline-none focus:ring-indigo-500"
            />
          </div>

          <div className="flex justify-end gap-3">
            <button
              type="button"
              onClick={onClose}
              disabled={loading}
              className="rounded-md border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={loading || !firRef.trim()}
              className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
            >
              {loading ? "Verifying..." : "Verify"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Component
// ---------------------------------------------------------------------------

/**
 * Renders the vehicle detail page for a single hotlist entry.
 * Shows complaint info, Leaflet map with sightings, and action buttons.
 */
export default function PoliceVehicleDetail(): React.JSX.Element {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { addToast } = useToast();

  const [entry, setEntry] = useState<HotlistDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Modal state
  const [firModalOpen, setFirModalOpen] = useState(false);
  const [firLoading, setFirLoading] = useState(false);
  const [firError, setFirError] = useState<string | null>(null);

  // Action loading states
  const [actionLoading, setActionLoading] = useState(false);

  // --- Fetch entry detail ---
  const fetchEntry = useCallback(async () => {
    if (!id) return;
    try {
      setLoading(true);
      setError(null);
      const data = (await apiRequest(`/hotlist/${id}`)) as HotlistDetail;
      setEntry(data);
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message);
      } else {
        setError("Failed to load vehicle details.");
      }
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    void fetchEntry();
  }, [fetchEntry]);

  // --- WebSocket subscription for live sighting updates ---
  useEffect(() => {
    if (!id) return;

    const unsubscribe = wsClient.subscribe((message: WsMessage) => {
      if (message.type === "new_sighting" && message.data) {
        const sighting = message.data as Record<string, unknown>;
        if (sighting.hotlist_id === id) {
          setEntry((prev) => {
            if (!prev) return prev;
            const newSighting: SightingInfo = {
              id: (sighting.id as string) ?? "",
              lat: (sighting.lat as number) ?? 0,
              lng: (sighting.lng as number) ?? 0,
              captured_at: (sighting.captured_at as string) ?? new Date().toISOString(),
              confidence: (sighting.confidence as number) ?? 0,
            };
            const updatedSightings = [newSighting, ...prev.sightings].slice(0, 50);
            return {
              ...prev,
              sightings: updatedSightings,
              last_seen_at: newSighting.captured_at,
              last_seen_lat: newSighting.lat,
              last_seen_lng: newSighting.lng,
            };
          });
        }
      }
    });

    return () => {
      unsubscribe();
    };
  }, [id]);

  // --- Actions ---
  const handleVerifyFir = async (firRef: string): Promise<void> => {
    if (!id) return;
    setFirLoading(true);
    setFirError(null);
    try {
      const updated = (await apiRequest(`/hotlist/${id}`, {
        method: "PUT",
        body: JSON.stringify({
          status: "ACTIVE_CONFIRMED",
          fir_ref: firRef,
          fir_verified_at: new Date().toISOString(),
        }),
      })) as HotlistDetail;
      setEntry((prev) => (prev ? { ...prev, ...updated } : prev));
      setFirModalOpen(false);
      addToast("FIR Verified", `FIR ref ${firRef} confirmed.`, "success");
    } catch (err) {
      if (err instanceof ApiError) {
        setFirError(err.message);
      } else {
        setFirError("Failed to verify FIR.");
      }
    } finally {
      setFirLoading(false);
    }
  };

  const handleMarkRecovered = async (): Promise<void> => {
    if (!id) return;
    setActionLoading(true);
    try {
      const updated = (await apiRequest(`/hotlist/${id}`, {
        method: "PUT",
        body: JSON.stringify({
          status: "CLOSED",
          recovered_at: new Date().toISOString(),
        }),
      })) as HotlistDetail;
      setEntry((prev) => (prev ? { ...prev, ...updated } : prev));
      addToast("Marked Recovered", "Vehicle marked as recovered.", "success");
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : "Failed to mark recovered.";
      addToast("Error", msg, "error");
    } finally {
      setActionLoading(false);
    }
  };

  const handleDismiss = async (): Promise<void> => {
    if (!id) return;
    setActionLoading(true);
    try {
      await apiRequest(`/hotlist/${id}`, {
        method: "PUT",
        body: JSON.stringify({ dismissed: true }),
      });
      setEntry((prev) => (prev ? { ...prev, dismissed: true } : prev));
      addToast("Dismissed", "Entry marked as false positive.", "info");
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : "Failed to dismiss.";
      addToast("Error", msg, "error");
    } finally {
      setActionLoading(false);
    }
  };

  const handleRemove = async (): Promise<void> => {
    if (!id) return;
    if (!window.confirm("Remove this entry from the hotlist? This action cannot be undone.")) {
      return;
    }
    setActionLoading(true);
    try {
      await apiRequest(`/hotlist/${id}`, { method: "DELETE" });
      addToast("Removed", "Entry removed from hotlist.", "success");
      navigate("/police", { replace: true });
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : "Failed to remove.";
      addToast("Error", msg, "error");
    } finally {
      setActionLoading(false);
    }
  };

  // --- Render ---
  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-gray-50">
        <p className="text-sm text-gray-500">Loading vehicle details...</p>
      </div>
    );
  }

  if (error || !entry) {
    return (
      <div className="mx-auto max-w-4xl px-4 py-8">
        <div className="rounded-md bg-red-50 p-4 text-sm text-red-700">
          {error ?? "Entry not found."}
        </div>
        <button
          onClick={() => navigate("/police")}
          className="mt-4 text-sm text-indigo-600 hover:text-indigo-800"
        >
          &larr; Back to Hotlist
        </button>
      </div>
    );
  }

  const sightings = entry.sightings;

  return (
    <div className="mx-auto max-w-5xl px-4 py-8">
      {/* Back link */}
      <button
        onClick={() => navigate("/police")}
        className="mb-4 text-sm text-indigo-600 hover:text-indigo-800"
      >
        &larr; Back to Hotlist
      </button>

      {/* Vehicle header */}
      <div className="mb-6 rounded-lg bg-white p-6 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h1 className="font-mono text-3xl font-bold text-gray-900">{entry.plate}</h1>
            <div className="mt-2 flex items-center gap-3">
              <span
                className={`inline-block rounded-full px-3 py-1 text-xs font-medium ${
                  STATUS_STYLES[entry.status] ?? "bg-gray-100 text-gray-800"
                }`}
              >
                {entry.status.replace(/_/g, " ")}
              </span>
              {entry.dismissed && (
                <span className="text-xs text-gray-500">(Dismissed)</span>
              )}
            </div>
          </div>
        </div>

        {/* Complaint info */}
        {entry.complaint && (
          <div className="mt-4 border-t border-gray-100 pt-4">
            <h3 className="text-sm font-medium text-gray-500">Complaint</h3>
            <p className="mt-1 text-sm text-gray-700">
              Filed: {formatDate(entry.complaint.created_at)}
            </p>
            <p className="text-sm text-gray-700">
              Status: {entry.complaint.status.replace(/_/g, " ")}
            </p>
            {entry.complaint.rejection_reason && (
              <p className="mt-1 text-sm text-red-600">
                Rejection reason: {entry.complaint.rejection_reason}
              </p>
            )}
          </div>
        )}

        {/* FIR info */}
        <div className="mt-4 border-t border-gray-100 pt-4">
          <h3 className="text-sm font-medium text-gray-500">FIR Details</h3>
          <p className="mt-1 text-sm text-gray-700">
            Reference: {entry.fir_ref ?? "Not provided"}
          </p>
          <p className="text-sm text-gray-700">
            Verified: {entry.fir_verified_at ? formatDate(entry.fir_verified_at) : "Not yet"}
          </p>
          <p className="text-sm text-gray-700">
            Deadline: {entry.fir_deadline ? formatDate(entry.fir_deadline) : "—"}
          </p>
        </div>
      </div>

      {/* Map */}
      <div className="mb-6 rounded-lg bg-white p-6 shadow-sm">
        <h2 className="mb-4 text-lg font-bold text-gray-900">Sighting Map</h2>
        <LeafletMap sightings={sightings} />
      </div>

      {/* Sighting list */}
      <div className="mb-6 rounded-lg bg-white p-6 shadow-sm">
        <h2 className="mb-4 text-lg font-bold text-gray-900">
          Sightings ({sightings.length})
        </h2>

        {sightings.length === 0 ? (
          <p className="text-sm text-gray-500">No sightings recorded yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead>
                <tr>
                  <th className="px-4 py-2 text-left text-xs font-medium uppercase text-gray-500">
                    #
                  </th>
                  <th className="px-4 py-2 text-left text-xs font-medium uppercase text-gray-500">
                    Time
                  </th>
                  <th className="px-4 py-2 text-left text-xs font-medium uppercase text-gray-500">
                    Location
                  </th>
                  <th className="px-4 py-2 text-left text-xs font-medium uppercase text-gray-500">
                    Confidence
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {sightings.map((sighting, index) => (
                  <tr key={sighting.id}>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-500">
                      {index + 1}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700">
                      {formatDate(sighting.captured_at)}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700">
                      {sighting.lat.toFixed(4)}, {sighting.lng.toFixed(4)}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700">
                      {sighting.confidence}%
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Actions */}
      <div className="rounded-lg bg-white p-6 shadow-sm">
        <h2 className="mb-4 text-lg font-bold text-gray-900">Actions</h2>
        <div className="flex flex-wrap gap-3">
          {(entry.status === "ACTIVE_UNCONFIRMED" || entry.status === "PENDING_VERIFICATION") && (
            <button
              onClick={() => {
                setFirError(null);
                setFirModalOpen(true);
              }}
              disabled={actionLoading}
              className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
            >
              Verify FIR
            </button>
          )}

          {entry.status !== "CLOSED" && entry.status !== "EXPIRED" && (
            <button
              onClick={handleMarkRecovered}
              disabled={actionLoading}
              className="rounded-md bg-green-600 px-4 py-2 text-sm font-medium text-white hover:bg-green-700 disabled:opacity-50"
            >
              Mark Recovered
            </button>
          )}

          {!entry.dismissed && entry.status !== "CLOSED" && (
            <button
              onClick={handleDismiss}
              disabled={actionLoading}
              className="rounded-md border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
            >
              Dismiss (False Positive)
            </button>
          )}

          {entry.status !== "CLOSED" && (
            <button
              onClick={handleRemove}
              disabled={actionLoading}
              className="rounded-md border border-red-300 bg-white px-4 py-2 text-sm font-medium text-red-700 hover:bg-red-50 disabled:opacity-50"
            >
              Remove
            </button>
          )}
        </div>
      </div>

      {/* FIR Verify Modal */}
      <FirVerifyModal
        isOpen={firModalOpen}
        onClose={() => setFirModalOpen(false)}
        onVerify={handleVerifyFir}
        loading={firLoading}
        error={firError}
      />
    </div>
  );
}
