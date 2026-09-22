/**
 * @module CitizenComplaint
 * Citizen complaint filing page — allows citizens to report stolen vehicles
 * with a licence plate, optional proof file, and notes. Also displays
 * the user's complaint history with status badges.
 */

import React, { useCallback, useEffect, useState } from "react";
import { apiRequest, ApiError } from "../lib/api";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** Accepted file types for proof upload. */
const ACCEPTED_FILE_TYPES = "image/*,video/*,.pdf";

/** Maximum file size in bytes (10 MB). */
const MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024;

/** Status badge colour mapping. */
const STATUS_STYLES: Record<string, string> = {
  PENDING_VERIFICATION: "bg-yellow-100 text-yellow-800",
  VERIFIED: "bg-green-100 text-green-800",
  REJECTED: "bg-red-100 text-red-800",
};

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface Complaint {
  id: string;
  user_id: string;
  plate: string;
  proof_ref: string | null;
  status: string;
  rejection_reason: string | null;
  created_at: string;
  updated_at: string;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

/**
 * Renders the complaint filing form and complaint history list.
 */
export default function CitizenComplaint(): React.JSX.Element {
  const [plate, setPlate] = useState("");
  const [notes, setNotes] = useState("");
  const [proofFile, setProofFile] = useState<File | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [submitSuccess, setSubmitSuccess] = useState<string | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const [complaints, setComplaints] = useState<Complaint[]>([]);
  const [loadingComplaints, setLoadingComplaints] = useState(true);
  const [complaintsError, setComplaintsError] = useState<string | null>(null);

  /** Fetch the user's complaints on mount. */
  const fetchComplaints = useCallback(async () => {
    try {
      setLoadingComplaints(true);
      const data = (await apiRequest("/complaints/mine")) as Complaint[];
      setComplaints(data);
    } catch (err) {
      if (err instanceof ApiError) {
        setComplaintsError(err.message);
      } else {
        setComplaintsError("Failed to load complaints.");
      }
    } finally {
      setLoadingComplaints(false);
    }
  }, []);

  useEffect(() => {
    fetchComplaints();
  }, [fetchComplaints]);

  /** Handle form submission — multipart POST to /complaints. */
  const handleSubmit = async (e: React.FormEvent): Promise<void> => {
    e.preventDefault();
    setSubmitError(null);
    setSubmitSuccess(null);
    setSubmitting(true);

    try {
      const formData = new FormData();
      formData.append("plate", plate.trim().toUpperCase());
      if (notes.trim()) {
        formData.append("notes", notes.trim());
      }
      if (proofFile) {
        if (proofFile.size > MAX_FILE_SIZE_BYTES) {
          throw new Error("File size must be under 10 MB.");
        }
        formData.append("proof", proofFile);
      }

      await apiRequest("/complaints/", {
        method: "POST",
        body: formData,
      });

      setSubmitSuccess("Complaint filed successfully.");
      setPlate("");
      setNotes("");
      setProofFile(null);

      // Refresh the complaint list.
      await fetchComplaints();
    } catch (err) {
      if (err instanceof ApiError) {
        setSubmitError(err.message);
      } else if (err instanceof Error) {
        setSubmitError(err.message);
      } else {
        setSubmitError("Failed to submit complaint. Please try again.");
      }
    } finally {
      setSubmitting(false);
    }
  };

  /** Format an ISO timestamp for display. */
  const formatDate = (iso: string): string => {
    return new Date(iso).toLocaleDateString("en-IN", {
      day: "numeric",
      month: "short",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  };

  return (
    <div className="mx-auto max-w-4xl px-4 py-8">
      <h1 className="mb-8 text-2xl font-bold text-gray-900">File a Complaint</h1>

      {/* ---------- Complaint Form ---------- */}
      <div className="rounded-lg bg-white p-6 shadow">
        {submitSuccess && (
          <div className="mb-4 rounded-md bg-green-50 p-3 text-sm text-green-700">
            {submitSuccess}
          </div>
        )}

        {submitError && (
          <div className="mb-4 rounded-md bg-red-50 p-3 text-sm text-red-700">
            {submitError}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label htmlFor="plate" className="block text-sm font-medium text-gray-700">
              Licence Plate Number
            </label>
            <input
              id="plate"
              type="text"
              required
              maxLength={20}
              placeholder="e.g. MH12AB1234"
              value={plate}
              onChange={(e) => setPlate(e.target.value)}
              className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 shadow-sm focus:border-indigo-500 focus:outline-none focus:ring-indigo-500"
            />
          </div>

          <div>
            <label htmlFor="notes" className="block text-sm font-medium text-gray-700">
              Notes (optional)
            </label>
            <textarea
              id="notes"
              rows={3}
              placeholder="Additional details about the incident..."
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 shadow-sm focus:border-indigo-500 focus:outline-none focus:ring-indigo-500"
            />
          </div>

          <div>
            <label htmlFor="proof" className="block text-sm font-medium text-gray-700">
              Proof File (optional — image, video, or PDF, max 10 MB)
            </label>
            <input
              id="proof"
              type="file"
              accept={ACCEPTED_FILE_TYPES}
              onChange={(e) => setProofFile(e.target.files?.[0] ?? null)}
              className="mt-1 block w-full text-sm text-gray-600 file:mr-4 file:rounded-md file:border-0 file:bg-indigo-600 file:px-4 file:py-2 file:text-sm file:font-medium file:text-white hover:file:bg-indigo-700"
            />
            {proofFile && (
              <p className="mt-1 text-xs text-gray-500">
                Selected: {proofFile.name} ({(proofFile.size / 1024).toFixed(1)} KB)
              </p>
            )}
          </div>

          <button
            type="submit"
            disabled={submitting}
            className="w-full rounded-md bg-indigo-600 px-4 py-2 text-white font-medium hover:bg-indigo-700 disabled:opacity-50"
          >
            {submitting ? "Submitting..." : "File Complaint"}
          </button>
        </form>
      </div>

      {/* ---------- Complaint History ---------- */}
      <h2 className="mt-10 mb-4 text-xl font-bold text-gray-900">Your Complaints</h2>

      {loadingComplaints && (
        <p className="text-sm text-gray-500">Loading complaints...</p>
      )}

      {complaintsError && (
        <div className="rounded-md bg-red-50 p-3 text-sm text-red-700">
          {complaintsError}
        </div>
      )}

      {!loadingComplaints && complaints.length === 0 && (
        <p className="text-sm text-gray-500">You have not filed any complaints yet.</p>
      )}

      {!loadingComplaints && complaints.length > 0 && (
        <div className="space-y-4">
          {complaints.map((c) => (
            <div
              key={c.id}
              className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm"
            >
              <div className="flex items-start justify-between">
                <div>
                  <p className="font-mono text-lg font-bold text-gray-900">{c.plate}</p>
                  <p className="text-xs text-gray-500">Filed {formatDate(c.created_at)}</p>
                </div>
                <span
                  className={`rounded-full px-3 py-1 text-xs font-medium ${
                    STATUS_STYLES[c.status] ?? "bg-gray-100 text-gray-800"
                  }`}
                >
                  {c.status.replace(/_/g, " ")}
                </span>
              </div>

              {c.rejection_reason && (
                <p className="mt-2 text-sm text-red-600">
                  Reason: {c.rejection_reason}
                </p>
              )}

              {c.proof_ref && (
                <p className="mt-1 text-xs text-gray-500">Proof attached</p>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
