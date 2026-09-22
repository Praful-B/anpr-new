/**
 * @module AdminPanel
 * Admin page — user management (list, filter, change role) and the audit log.
 *
 * Talks to `GET /admin/users`, `PATCH /admin/users/{id}/role`, and
 * `GET /admin/audit`. Visible only to ADMIN users via ProtectedRoute.
 */

import React, { useCallback, useEffect, useState } from "react";
import { apiRequest, ApiError } from "../lib/api";
import { useToast } from "../components/Toast";
import { useAuth } from "../lib/auth";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** Page size used for both tables. */
const PAGE_SIZE = 20;

/** Roles a user can be assigned. */
const ROLES = ["CITIZEN", "VOLUNTEER", "COP", "ADMIN"] as const;

/** Tab identifiers. */
type Tab = "users" | "audit";

/** Shape of a user row from the admin API. */
interface AdminUser {
  readonly id: string;
  readonly name: string;
  readonly email: string;
  readonly phone: string | null;
  readonly role: string;
  readonly created_at: string;
}

/** Shape of an audit row from the admin API. */
interface AuditEntry {
  readonly id: string;
  readonly actor_id: string;
  readonly action: string;
  readonly target_type: string;
  readonly target_id: string;
  readonly metadata: Record<string, unknown> | null;
  readonly created_at: string;
}

/** Paginated envelope returned by both admin list endpoints. */
interface PageResponse<T> {
  readonly items: T[];
  readonly total: number;
  readonly page: number;
  readonly per_page: number;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Format an ISO timestamp for display.
 *
 * @param iso - ISO timestamp string.
 * @returns A locale-formatted date-time, or an em dash when absent.
 */
function formatDate(iso: string): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-IN", {
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
 * Admin panel with a users table and an audit-log table.
 *
 * @returns The admin page JSX.
 */
export default function AdminPanel(): React.JSX.Element {
  const { user } = useAuth();
  const { addToast } = useToast();

  const [activeTab, setActiveTab] = useState<Tab>("users");
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [userTotal, setUserTotal] = useState(0);
  const [userPage, setUserPage] = useState(1);
  const [roleFilter, setRoleFilter] = useState("");
  const [auditEntries, setAuditEntries] = useState<AuditEntry[]>([]);
  const [auditTotal, setAuditTotal] = useState(0);
  const [auditPage, setAuditPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [busyUserId, setBusyUserId] = useState<string | null>(null);

  const loadUsers = useCallback(async (): Promise<void> => {
    try {
      const params = new URLSearchParams({
        page: String(userPage),
        per_page: String(PAGE_SIZE),
      });
      if (roleFilter) params.set("role", roleFilter);
      const data = (await apiRequest(`/admin/users?${params.toString()}`)) as PageResponse<AdminUser>;
      setUsers(data.items);
      setUserTotal(data.total);
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "Failed to load users.";
      addToast("Error", message, "error");
    }
  }, [userPage, roleFilter, addToast]);

  const loadAudit = useCallback(async (): Promise<void> => {
    try {
      const params = new URLSearchParams({
        page: String(auditPage),
        per_page: String(PAGE_SIZE),
      });
      const data = (await apiRequest(`/admin/audit?${params.toString()}`)) as PageResponse<AuditEntry>;
      setAuditEntries(data.items);
      setAuditTotal(data.total);
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "Failed to load audit log.";
      addToast("Error", message, "error");
    }
  }, [auditPage, addToast]);

  useEffect(() => {
    const load = async (): Promise<void> => {
      setLoading(true);
      await Promise.all([loadUsers(), loadAudit()]);
      setLoading(false);
    };
    load();
  }, [loadUsers, loadAudit]);

  const handleRoleChange = useCallback(
    async (userId: string, role: string): Promise<void> => {
      setBusyUserId(userId);
      try {
        await apiRequest(`/admin/users/${userId}/role`, {
          method: "PATCH",
          body: JSON.stringify({ role }),
        });
        addToast("Role Updated", `User role changed to ${role}.`, "success");
        await Promise.all([loadUsers(), loadAudit()]);
      } catch (err) {
        const message = err instanceof ApiError ? err.message : "Failed to change role.";
        addToast("Error", message, "error");
      } finally {
        setBusyUserId(null);
      }
    },
    [addToast, loadUsers, loadAudit],
  );

  const userTotalPages = Math.max(1, Math.ceil(userTotal / PAGE_SIZE));
  const auditTotalPages = Math.max(1, Math.ceil(auditTotal / PAGE_SIZE));

  return (
    <div className="min-h-screen bg-gray-50 p-6">
      <header className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Admin Panel</h1>
          <p className="text-sm text-gray-500">
            Signed in as {user?.role ?? "ADMIN"}
          </p>
        </div>
        <nav className="flex gap-2">
          <a href="/police" className="rounded bg-white px-3 py-2 text-sm text-gray-700 shadow">
            Hotlist
          </a>
          <a href="/analytics" className="rounded bg-white px-3 py-2 text-sm text-gray-700 shadow">
            Analytics
          </a>
        </nav>
      </header>

      <div className="mb-4 flex gap-4 border-b border-gray-200">
        <button
          type="button"
          onClick={() => setActiveTab("users")}
          className={`pb-2 text-sm font-medium ${
            activeTab === "users" ? "border-b-2 border-blue-600 text-blue-600" : "text-gray-500"
          }`}
        >
          Users ({userTotal})
        </button>
        <button
          type="button"
          onClick={() => setActiveTab("audit")}
          className={`pb-2 text-sm font-medium ${
            activeTab === "audit" ? "border-b-2 border-blue-600 text-blue-600" : "text-gray-500"
          }`}
        >
          Audit Log ({auditTotal})
        </button>
      </div>

      {loading ? (
        <p className="text-sm text-gray-500">Loading...</p>
      ) : activeTab === "users" ? (
        <section>
          <label className="mb-3 block text-sm text-gray-600">
            Filter by role
            <select
              value={roleFilter}
              onChange={(event) => {
                setRoleFilter(event.target.value);
                setUserPage(1);
              }}
              className="ml-2 rounded border border-gray-300 px-2 py-1"
            >
              <option value="">All</option>
              {ROLES.map((role) => (
                <option key={role} value={role}>
                  {role}
                </option>
              ))}
            </select>
          </label>

          <table className="w-full overflow-hidden rounded bg-white shadow">
            <thead className="bg-gray-100 text-left text-xs uppercase text-gray-600">
              <tr>
                <th className="px-4 py-3">Name</th>
                <th className="px-4 py-3">Email</th>
                <th className="px-4 py-3">Role</th>
                <th className="px-4 py-3">Created</th>
                <th className="px-4 py-3">Change role</th>
              </tr>
            </thead>
            <tbody>
              {users.map((row) => (
                <tr key={row.id} className="border-t border-gray-100">
                  <td className="px-4 py-3 text-sm text-gray-900">{row.name}</td>
                  <td className="px-4 py-3 text-sm text-gray-600">{row.email}</td>
                  <td className="px-4 py-3 text-sm font-medium text-gray-800">{row.role}</td>
                  <td className="px-4 py-3 text-sm text-gray-500">
                    {formatDate(row.created_at)}
                  </td>
                  <td className="px-4 py-3">
                    <select
                      value={row.role}
                      disabled={busyUserId === row.id}
                      onChange={(event) => handleRoleChange(row.id, event.target.value)}
                      className="rounded border border-gray-300 px-2 py-1 text-sm"
                    >
                      {ROLES.map((role) => (
                        <option key={role} value={role}>
                          {role}
                        </option>
                      ))}
                    </select>
                  </td>
                </tr>
              ))}
              {users.length === 0 ? (
                <tr>
                  <td colSpan={5} className="px-4 py-6 text-center text-sm text-gray-500">
                    No users match this filter.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>

          <div className="mt-4 flex items-center justify-between text-sm text-gray-600">
            <span>
              Page {userPage} of {userTotalPages} ({userTotal} users)
            </span>
            <div className="flex gap-2">
              <button
                type="button"
                disabled={userPage <= 1}
                onClick={() => setUserPage((page) => Math.max(1, page - 1))}
                className="rounded border border-gray-300 bg-white px-3 py-1 disabled:opacity-40"
              >
                &larr; Prev
              </button>
              <button
                type="button"
                disabled={userPage >= userTotalPages}
                onClick={() => setUserPage((page) => page + 1)}
                className="rounded border border-gray-300 bg-white px-3 py-1 disabled:opacity-40"
              >
                Next &rarr;
              </button>
            </div>
          </div>
        </section>
      ) : (
        <section>
          <table className="w-full overflow-hidden rounded bg-white shadow">
            <thead className="bg-gray-100 text-left text-xs uppercase text-gray-600">
              <tr>
                <th className="px-4 py-3">Action</th>
                <th className="px-4 py-3">Target</th>
                <th className="px-4 py-3">Actor</th>
                <th className="px-4 py-3">When</th>
              </tr>
            </thead>
            <tbody>
              {auditEntries.map((row) => (
                <tr key={row.id} className="border-t border-gray-100">
                  <td className="px-4 py-3 text-sm font-medium text-gray-900">{row.action}</td>
                  <td className="px-4 py-3 text-sm text-gray-600">
                    {row.target_type}:{row.target_id.slice(0, 8)}
                  </td>
                  <td className="px-4 py-3 text-sm text-gray-600">
                    {row.actor_id.slice(0, 8)}
                  </td>
                  <td className="px-4 py-3 text-sm text-gray-500">
                    {formatDate(row.created_at)}
                  </td>
                </tr>
              ))}
              {auditEntries.length === 0 ? (
                <tr>
                  <td colSpan={4} className="px-4 py-6 text-center text-sm text-gray-500">
                    No audit entries recorded yet.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>

          <div className="mt-4 flex items-center justify-between text-sm text-gray-600">
            <span>
              Page {auditPage} of {auditTotalPages} ({auditTotal} entries)
            </span>
            <div className="flex gap-2">
              <button
                type="button"
                disabled={auditPage <= 1}
                onClick={() => setAuditPage((page) => Math.max(1, page - 1))}
                className="rounded border border-gray-300 bg-white px-3 py-1 disabled:opacity-40"
              >
                &larr; Prev
              </button>
              <button
                type="button"
                disabled={auditPage >= auditTotalPages}
                onClick={() => setAuditPage((page) => page + 1)}
                className="rounded border border-gray-300 bg-white px-3 py-1 disabled:opacity-40"
              >
                Next &rarr;
              </button>
            </div>
          </div>
        </section>
      )}
    </div>
  );
}
