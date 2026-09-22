/**
 * @module PoliceAnalytics
 * Full analytics dashboard page for COP/ADMIN users.
 *
 * Displays six widgets in a single scrolling layout:
 *   Row 1 — 4 KPI cards (overview metrics)
 *   Row 2 — Leaflet heatmap with date range picker
 *   Row 3 — Recovery metrics line chart + false-positive rate donut
 *   Row 4 — Sightings by hour bar chart + sightings by day-of-week bar chart
 *   Row 5 — Device coverage sortable table
 *
 * All widgets re-fetch when the shared date range changes.
 */

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  LineChart,
  Line,
  BarChart,
  Bar,
  PieChart,
  Pie,
  Cell,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";
import L from "leaflet";
import "leaflet.heat";
import { apiRequest, ApiError } from "../lib/api";
import DateRangePicker, { type DateRange } from "../components/DateRangePicker";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** Overview metrics returned by GET /analytics/overview. */
interface OverviewData {
  total_active_hotlist: number;
  total_sightings_last_24h: number;
  total_sightings_last_7d: number;
  total_recoveries_last_30d: number;
  avg_time_to_first_sighting_hours: number | null;
  avg_time_to_recovery_hours: number | null;
}

/** A single heatmap bucket from GET /analytics/heatmap. */
interface HeatmapPoint {
  lat: number;
  lng: number;
  weight: number;
}

/** A single row in the recovery-metrics time series. */
interface RecoveryWeek {
  week_start: string;
  hotlist_added: number;
  recovered: number;
  expired: number;
  recovery_rate: number;
}

/** False-positive rate response from GET /analytics/false-positive-rate. */
interface FalsePositiveData {
  total_hits: number;
  hits_dismissed_by_officer: number;
  fp_rate: number;
  per_device: FalsePositiveDevice[];
}

/** Per-device false-positive breakdown. */
interface FalsePositiveDevice {
  device_id: string;
  total_hits: number;
  hits_dismissed: number;
  fp_rate: number;
}

/** Device coverage response from GET /analytics/device-coverage. */
interface DeviceCoverageData {
  total: number;
  active_last_24h: number;
  revoked: number;
  devices: DeviceRow[];
}

/** A single device row in the coverage table. */
interface DeviceRow {
  device_id: string;
  type: string;
  revoked: boolean;
  last_sync_at: string | null;
  total_sightings: number;
  last_active: string | null;
}

/** Time patterns response from GET /analytics/time-patterns. */
interface TimePatternsData {
  by_hour: number[];
  by_day: number[];
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** Default map centre — India. */
const DEFAULT_CENTER: L.LatLngTuple = [20.5937, 78.9629];

/** Default map zoom level. */
const DEFAULT_ZOOM = 5;

/** Day-of-week labels for bar chart (Sunday = 0). */
const DAY_LABELS: readonly string[] = [
  "Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat",
] as const;

/** Hour labels for bar chart (00–23). */
const HOUR_LABELS: readonly string[] = Array.from(
  { length: 24 },
  (_, i) => String(i).padStart(2, "0"),
) as readonly string[];

/** Colour palette for pie chart slices. */
const PIE_COLOURS: readonly string[] = ["#22c55e", "#ef4444"] as const;

/** Tooltip style shared by all charts. */
const TOOLTIP_STYLE: React.CSSProperties = {
  backgroundColor: "#fff",
  border: "1px solid #e5e7eb",
  borderRadius: "0.375rem",
  padding: "0.5rem 0.75rem",
  fontSize: "0.8125rem",
};

/** Max heatmap point radius. */
const HEAT_RADIUS = 25;

/** Max heatmap blur. */
const HEAT_BLUR = 15;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Build a query string from a date range.
 *
 * @param range - The current from/to range.
 * @returns URL search params string (may be empty).
 */
function buildQueryString(range: DateRange): string {
  const params = new URLSearchParams();
  if (range.from) params.set("from", range.from);
  if (range.to) params.set("to", range.to);
  return params.toString();
}

/**
 * Format an hours value as "Xh Ym" or "N/A".
 *
 * @param hours - Number of hours, or null.
 * @returns Human-readable string.
 */
function formatHours(hours: number | null): string {
  if (hours === null || hours === undefined) return "N/A";
  const h = Math.floor(hours);
  const m = Math.round((hours - h) * 60);
  if (h === 0 && m === 0) return "0m";
  return m > 0 ? `${h}h ${m}m` : `${h}h`;
}

/**
 * Format a timestamp for display in the device table.
 *
 * @param iso - ISO timestamp string, or null.
 * @returns Formatted date string or "—".
 */
function formatTimestamp(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("en-IN", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/**
 * Render an empty state message.
 *
 * @param message - The message to display.
 * @returns A centred placeholder element.
 */
function EmptyState({ message }: { readonly message: string }): React.JSX.Element {
  return (
    <div className="flex h-48 items-center justify-center text-sm text-gray-500">
      {message}
    </div>
  );
}

/**
 * Render a single KPI card.
 *
 * @param title  - Card heading.
 * @param value  - Primary metric display.
 * @param subtitle - Secondary metric display.
 * @returns A styled card element.
 */
function KpiCard({
  title,
  value,
  subtitle,
}: {
  readonly title: string;
  readonly value: string | number;
  readonly subtitle: string;
}): React.JSX.Element {
  return (
    <div className="rounded-lg bg-white p-5 shadow-sm">
      <h3 className="text-sm font-medium text-gray-500">{title}</h3>
      <p className="mt-2 text-3xl font-bold text-gray-900">{value}</p>
      <p className="mt-1 text-sm text-gray-500">{subtitle}</p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Custom hook: useAnalyticsQuery
// ---------------------------------------------------------------------------

/**
 * Generic fetcher for analytics endpoints.
 *
 * @param endpoint - API path (e.g. `/analytics/overview`).
 * @param range    - Current date range.
 * @param deps     - Additional dependencies that trigger re-fetch.
 * @returns The parsed response body, or null on error / loading.
 */
function useAnalyticsQuery<T>(
  endpoint: string,
  range: DateRange,
): {
  data: T | null;
  loading: boolean;
  error: string | null;
} {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const queryString = useMemo(() => buildQueryString(range), [range]);
  const url = queryString ? `${endpoint}?${queryString}` : endpoint;

  useEffect(() => {
    let cancelled = false;

    async function fetchData(): Promise<void> {
      setLoading(true);
      setError(null);
      try {
        const result = (await apiRequest(url)) as T;
        if (!cancelled) setData(result);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof ApiError ? err.message : "Failed to load data.");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    fetchData();
    return () => { cancelled = true; };
  }, [url]);

  return { data, loading, error };
}

// ---------------------------------------------------------------------------
// Sub-component: Row 1 — Overview KPI cards
// ---------------------------------------------------------------------------

/** Empty overview when no data is available. */
const EMPTY_OVERVIEW: OverviewData = {
  total_active_hotlist: 0,
  total_sightings_last_24h: 0,
  total_sightings_last_7d: 0,
  total_recoveries_last_30d: 0,
  avg_time_to_first_sighting_hours: null,
  avg_time_to_recovery_hours: null,
};

/**
 * Fetches and renders the four overview KPI cards.
 *
 * @param range - The active date range.
 * @returns The KPI card row.
 */
function OverviewRow({ range }: { readonly range: DateRange }): React.JSX.Element {
  const { data, loading, error } = useAnalyticsQuery<OverviewData>(
    "/analytics/overview",
    range,
  );

  const overview = data ?? EMPTY_OVERVIEW;

  if (loading) {
    return (
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="animate-pulse rounded-lg bg-white p-5 shadow-sm">
            <div className="h-4 w-24 rounded bg-gray-200" />
            <div className="mt-3 h-8 w-16 rounded bg-gray-200" />
            <div className="mt-2 h-3 w-32 rounded bg-gray-200" />
          </div>
        ))}
      </div>
    );
  }

  if (error) {
    return <div className="rounded-md bg-red-50 p-3 text-sm text-red-700">{error}</div>;
  }

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
      <KpiCard
        title="Active Hotlist"
        value={overview.total_active_hotlist}
        subtitle="Vehicles currently tracked"
      />
      <KpiCard
        title="Sightings (24h)"
        value={overview.total_sightings_last_24h}
        subtitle={`${overview.total_sightings_last_7d} in last 7 days`}
      />
      <KpiCard
        title="Recoveries (30d)"
        value={overview.total_recoveries_last_30d}
        subtitle="Vehicles recovered"
      />
      <KpiCard
        title="Avg Time to First Sighting"
        value={formatHours(overview.avg_time_to_first_sighting_hours)}
        subtitle={`Recovery: ${formatHours(overview.avg_time_to_recovery_hours)}`}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub-component: Row 2 — Leaflet heatmap
// ---------------------------------------------------------------------------

/**
 * Renders a Leaflet heatmap fed by /analytics/heatmap.
 *
 * @param range - The active date range.
 * @returns The heatmap widget with loading/empty/error states.
 */
function HeatmapRow({ range }: { readonly range: DateRange }): React.JSX.Element {
  const { data, loading, error } = useAnalyticsQuery<HeatmapPoint[]>(
    "/analytics/heatmap",
    range,
  );
  const mapRef = useRef<HTMLDivElement>(null);
  const mapInstanceRef = useRef<L.Map | null>(null);
  const heatLayerRef = useRef<L.HeatLayer | null>(null);

  const centreMap = useCallback(() => {
    if (!mapRef.current || mapInstanceRef.current) return;

    const map = L.map(mapRef.current, {
      center: DEFAULT_CENTER,
      zoom: DEFAULT_ZOOM,
      zoomControl: true,
      attributionControl: true,
    });

    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution: '&copy; <a href="https://osm.org/copyright">OSM</a>',
    }).addTo(map);

    mapInstanceRef.current = map;
  }, []);

  useEffect(() => {
    centreMap();
  }, [centreMap]);

  useEffect(() => {
    if (!mapInstanceRef.current || !data) return;

    if (heatLayerRef.current) {
      mapInstanceRef.current.removeLayer(heatLayerRef.current);
    }

    if (data.length === 0) {
      heatLayerRef.current = null;
      return;
    }

    const points: Array<[number, number, number]> = data.map((p) => [
      p.lat,
      p.lng,
      p.weight,
    ]);

    const layer = L.heatLayer(points, {
      radius: HEAT_RADIUS,
      blur: HEAT_BLUR,
      maxZoom: 10,
    }).addTo(mapInstanceRef.current);

    heatLayerRef.current = layer;
  }, [data]);

  return (
    <div className="rounded-lg bg-white p-5 shadow-sm">
      <h2 className="mb-3 text-lg font-semibold text-gray-900">
        Sighting Heatmap
      </h2>
      {error && (
        <div className="mb-3 rounded-md bg-red-50 p-3 text-sm text-red-700">
          {error}
        </div>
      )}
      {loading ? (
        <div className="flex h-80 items-center justify-center">
          <span className="text-sm text-gray-500">Loading heatmap...</span>
        </div>
      ) : !data || data.length === 0 ? (
        <EmptyState message="No data for selected range." />
      ) : (
        <div ref={mapRef} className="h-80 w-full rounded-md" />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub-component: Row 3 — Recovery metrics line chart
// ---------------------------------------------------------------------------

/**
 * Fetches and renders the recovery metrics line chart.
 *
 * @param range - The active date range.
 * @returns A Recharts LineChart showing weekly added/recovered/expired.
 */
function RecoveryMetricsChart({ range }: { readonly range: DateRange }): React.JSX.Element {
  const { data, loading, error } = useAnalyticsQuery<RecoveryWeek[]>(
    "/analytics/recovery-metrics",
    range,
  );

  if (loading) {
    return (
      <div className="rounded-lg bg-white p-5 shadow-sm">
        <div className="h-64 animate-pulse rounded bg-gray-100" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-lg bg-white p-5 shadow-sm">
        <div className="rounded-md bg-red-50 p-3 text-sm text-red-700">{error}</div>
      </div>
    );
  }

  if (!data || data.length === 0) {
    return (
      <div className="rounded-lg bg-white p-5 shadow-sm">
        <h2 className="mb-3 text-lg font-semibold text-gray-900">
          Recovery Metrics
        </h2>
        <EmptyState message="No data for selected range." />
      </div>
    );
  }

  return (
    <div className="rounded-lg bg-white p-5 shadow-sm">
      <h2 className="mb-3 text-lg font-semibold text-gray-900">
        Recovery Metrics (Weekly)
      </h2>
      <ResponsiveContainer width="100%" height={300}>
        <LineChart data={data}>
          <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
          <XAxis dataKey="week_start" tick={{ fontSize: 11 }} />
          <YAxis tick={{ fontSize: 11 }} />
          <Tooltip contentStyle={TOOLTIP_STYLE} />
          <Legend />
          <Line
            type="monotone"
            dataKey="hotlist_added"
            name="Added"
            stroke="#6366f1"
            strokeWidth={2}
            dot={false}
          />
          <Line
            type="monotone"
            dataKey="recovered"
            name="Recovered"
            stroke="#22c55e"
            strokeWidth={2}
            dot={false}
          />
          <Line
            type="monotone"
            dataKey="expired"
            name="Expired"
            stroke="#ef4444"
            strokeWidth={2}
            dot={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub-component: Row 3 — False-positive rate donut
// ---------------------------------------------------------------------------

/** Shape for the Recharts PieChart data. */
interface PieSlice {
  name: string;
  value: number;
}

/**
 * Fetches and renders the false-positive rate donut chart.
 *
 * @param range - The active date range.
 * @returns A Recharts PieChart showing confirmed vs false-positive hits.
 */
function FalsePositiveChart({ range }: { readonly range: DateRange }): React.JSX.Element {
  const { data, loading, error } = useAnalyticsQuery<FalsePositiveData>(
    "/analytics/false-positive-rate",
    range,
  );

  if (loading) {
    return (
      <div className="rounded-lg bg-white p-5 shadow-sm">
        <div className="h-64 animate-pulse rounded bg-gray-100" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-lg bg-white p-5 shadow-sm">
        <div className="rounded-md bg-red-50 p-3 text-sm text-red-700">{error}</div>
      </div>
    );
  }

  if (!data || data.total_hits === 0) {
    return (
      <div className="rounded-lg bg-white p-5 shadow-sm">
        <h2 className="mb-3 text-lg font-semibold text-gray-900">
          False Positive Rate
        </h2>
        <EmptyState message="No data for selected range." />
      </div>
    );
  }

  const confirmed = data.total_hits - data.hits_dismissed_by_officer;
  const slices: PieSlice[] = [
    { name: "Confirmed", value: confirmed },
    { name: "Dismissed (FP)", value: data.hits_dismissed_by_officer },
  ];

  return (
    <div className="rounded-lg bg-white p-5 shadow-sm">
      <h2 className="mb-3 text-lg font-semibold text-gray-900">
        False Positive Rate
      </h2>
      <ResponsiveContainer width="100%" height={300}>
        <PieChart>
          <Pie
            data={slices}
            cx="50%"
            cy="50%"
            innerRadius={60}
            outerRadius={100}
            paddingAngle={2}
            dataKey="value"
            label={(props) =>
              `${props.name ?? "Unknown"} ${((props.percent ?? 0) * 100).toFixed(0)}%`
            }
          >
            {slices.map((_entry, index) => (
              <Cell key={`cell-${index}`} fill={PIE_COLOURS[index]} />
            ))}
          </Pie>
          <Tooltip contentStyle={TOOLTIP_STYLE} />
          <Legend />
        </PieChart>
      </ResponsiveContainer>
      <p className="mt-2 text-center text-sm text-gray-500">
        Overall FP rate: {data.fp_rate}%
      </p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub-component: Row 4 — Sightings by hour bar chart
// ---------------------------------------------------------------------------

/** Shape for the by-hour bar chart. */
interface HourBucket {
  hour: string;
  count: number;
}

/**
 * Fetches and renders two bar charts: sightings by hour and by day of week.
 *
 * @param range - The active date range.
 * @returns Two side-by-side bar charts.
 */
function TimePatternsRow({ range }: { readonly range: DateRange }): React.JSX.Element {
  const { data, loading, error } = useAnalyticsQuery<TimePatternsData>(
    "/analytics/time-patterns",
    range,
  );

  const hourData = useMemo<HourBucket[]>(() => {
    if (!data) return [];
    return data.by_hour.map((count, i) => ({
      hour: HOUR_LABELS[i],
      count,
    }));
  }, [data]);

  const dayData = useMemo(() => {
    if (!data) return [];
    return data.by_day.map((count, i) => ({
      day: DAY_LABELS[i],
      count,
    }));
  }, [data]);

  if (loading) {
    return (
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {Array.from({ length: 2 }).map((_, i) => (
          <div key={i} className="rounded-lg bg-white p-5 shadow-sm">
            <div className="h-64 animate-pulse rounded bg-gray-100" />
          </div>
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-md bg-red-50 p-3 text-sm text-red-700">{error}</div>
    );
  }

  if (!data) {
    return (
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {Array.from({ length: 2 }).map((_, i) => (
          <div key={i} className="rounded-lg bg-white p-5 shadow-sm">
            <EmptyState message="No data for selected range." />
          </div>
        ))}
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      <div className="rounded-lg bg-white p-5 shadow-sm">
        <h2 className="mb-3 text-lg font-semibold text-gray-900">
          Sightings by Hour
        </h2>
        <ResponsiveContainer width="100%" height={300}>
          <BarChart data={hourData}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
            <XAxis dataKey="hour" tick={{ fontSize: 10 }} />
            <YAxis tick={{ fontSize: 11 }} />
            <Tooltip contentStyle={TOOLTIP_STYLE} />
            <Bar dataKey="count" name="Sightings" fill="#6366f1" radius={[2, 2, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <div className="rounded-lg bg-white p-5 shadow-sm">
        <h2 className="mb-3 text-lg font-semibold text-gray-900">
          Sightings by Day of Week
        </h2>
        <ResponsiveContainer width="100%" height={300}>
          <BarChart data={dayData}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
            <XAxis dataKey="day" tick={{ fontSize: 11 }} />
            <YAxis tick={{ fontSize: 11 }} />
            <Tooltip contentStyle={TOOLTIP_STYLE} />
            <Bar dataKey="count" name="Sightings" fill="#8b5cf6" radius={[2, 2, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub-component: Row 5 — Device coverage table
// ---------------------------------------------------------------------------

/** Sortable columns for the device table. */
type DeviceSortKey = "device_id" | "type" | "total_sightings" | "last_sync_at" | "revoked";

/** Sort direction. */
type SortDir = "asc" | "desc";

/** Sort state for the device table. */
interface DeviceSort {
  key: DeviceSortKey;
  dir: SortDir;
}

/**
 * Compare two device rows by the given sort key and direction.
 *
 * @param a     - First device row.
 * @param b     - Second device row.
 * @param sort  - Sort configuration.
 * @returns Negative if a < b, positive if a > b.
 */
function compareDevices(a: DeviceRow, b: DeviceRow, sort: DeviceSort): number {
  const valA = a[sort.key];
  const valB = b[sort.key];
  const cmp = String(valA).localeCompare(String(valB), undefined, { numeric: true });
  return sort.dir === "asc" ? cmp : -cmp;
}

/**
 * Render the device coverage table with sortable columns.
 *
 * @param coverage - The device coverage data.
 * @returns A sortable HTML table.
 */
function DeviceTable({ coverage }: { readonly coverage: DeviceCoverageData }): React.JSX.Element {
  const [sort, setSort] = useState<DeviceSort>({ key: "total_sightings", dir: "desc" });

  const handleSort = useCallback(
    (key: DeviceSortKey) => {
      setSort((prev) => ({
        key,
        dir: prev.key === key && prev.dir === "desc" ? "asc" : "desc",
      }));
    },
    [],
  );

  const sorted = useMemo(
    () => [...coverage.devices].sort((a, b) => compareDevices(a, b, sort)),
    [coverage.devices, sort],
  );

  const sortIndicator = (key: DeviceSortKey): string => {
    if (sort.key !== key) return " \u2195";
    return sort.dir === "desc" ? " \u2193" : " \u2191";
  };

  return (
    <div className="overflow-x-auto rounded-lg bg-white shadow-sm">
      <div className="mb-3 flex gap-4 px-5 pt-5 text-sm text-gray-500">
        <span>Total: <strong className="text-gray-900">{coverage.total}</strong></span>
        <span>Active (24h): <strong className="text-gray-900">{coverage.active_last_24h}</strong></span>
        <span>Revoked: <strong className="text-gray-900">{coverage.revoked}</strong></span>
      </div>
      <table className="min-w-full divide-y divide-gray-200">
        <thead className="bg-gray-50">
          <tr>
            {(["device_id", "type", "total_sightings", "last_sync_at", "revoked"] as const).map(
              (col) => (
                <th
                  key={col}
                  onClick={() => handleSort(col)}
                  className="cursor-pointer whitespace-nowrap px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500 hover:text-gray-700"
                >
                  {col === "total_sightings" ? "Hits" : col.replace(/_/g, " ")}
                  {sortIndicator(col)}
                </th>
              ),
            )}
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-200 bg-white">
          {sorted.map((device) => (
            <tr key={device.device_id} className="hover:bg-gray-50">
              <td className="whitespace-nowrap px-6 py-4 font-mono text-sm text-gray-900">
                {device.device_id.slice(0, 8)}...
              </td>
              <td className="whitespace-nowrap px-6 py-4 text-sm text-gray-600">
                {device.type}
              </td>
              <td className="whitespace-nowrap px-6 py-4 text-sm font-medium text-gray-900">
                {device.total_sightings}
              </td>
              <td className="whitespace-nowrap px-6 py-4 text-sm text-gray-600">
                {formatTimestamp(device.last_sync_at)}
              </td>
              <td className="whitespace-nowrap px-6 py-4">
                <span
                  className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-medium ${
                    device.revoked
                      ? "bg-red-100 text-red-800"
                      : "bg-green-100 text-green-800"
                  }`}
                >
                  {device.revoked ? "Revoked" : "Active"}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * Fetches and renders the device coverage table.
 *
 * @param range - The active date range.
 * @returns The device coverage table or loading/empty state.
 */
function DeviceCoverageRow({ range }: { readonly range: DateRange }): React.JSX.Element {
  const { data, loading, error } = useAnalyticsQuery<DeviceCoverageData>(
    "/analytics/device-coverage",
    range,
  );

  if (loading) {
    return (
      <div className="rounded-lg bg-white p-5 shadow-sm">
        <div className="h-48 animate-pulse rounded bg-gray-100" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-md bg-red-50 p-3 text-sm text-red-700">{error}</div>
    );
  }

  if (!data || data.devices.length === 0) {
    return (
      <div className="rounded-lg bg-white p-5 shadow-sm">
        <h2 className="mb-3 text-lg font-semibold text-gray-900">
          Device Coverage
        </h2>
        <EmptyState message="No data for selected range." />
      </div>
    );
  }

  return (
    <div>
      <h2 className="mb-3 text-lg font-semibold text-gray-900">Device Coverage</h2>
      <DeviceTable coverage={data} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

/**
 * PoliceAnalytics — the full analytics dashboard page.
 *
 * Composes all five rows: overview KPIs, heatmap, recovery + FP charts,
 * time-pattern charts, and the device coverage table. A shared date
 * range picker at the top controls which data window all widgets query.
 *
 * @returns A single scrolling analytics page.
 */
export default function PoliceAnalytics(): React.JSX.Element {
  const [dateRange, setDateRange] = useState<DateRange>({ from: "", to: "" });

  const handleRangeChange = useCallback((range: DateRange) => {
    setDateRange(range);
  }, []);

  return (
    <div className="mx-auto max-w-7xl space-y-6 px-4 py-8">
      <h1 className="text-2xl font-bold text-gray-900">Analytics</h1>

      {/* Date range picker */}
      <div className="rounded-lg bg-white p-4 shadow-sm">
        <DateRangePicker value={dateRange} onChange={handleRangeChange} />
      </div>

      {/* Row 1 — KPI cards */}
      <OverviewRow range={dateRange} />

      {/* Row 2 — Heatmap */}
      <HeatmapRow range={dateRange} />

      {/* Row 3 — Recovery metrics + False positive rate */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <RecoveryMetricsChart range={dateRange} />
        <FalsePositiveChart range={dateRange} />
      </div>

      {/* Row 4 — Time patterns */}
      <TimePatternsRow range={dateRange} />

      {/* Row 5 — Device coverage */}
      <DeviceCoverageRow range={dateRange} />
    </div>
  );
}
