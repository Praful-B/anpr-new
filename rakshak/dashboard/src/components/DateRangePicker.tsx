/**
 * @module DateRangePicker
 * Shared date range picker component used across analytics charts.
 * Renders "from" and "to" date inputs and calls the parent callback
 * whenever the selected range changes.
 */

import React, { useCallback } from "react";

/** Shape of the date range state. */
export interface DateRange {
  /** ISO date string for the start of the range (YYYY-MM-DD), or empty. */
  from: string;
  /** ISO date string for the end of the range (YYYY-MM-DD), or empty. */
  to: string;
}

interface DateRangePickerProps {
  /** Current date range value. */
  value: DateRange;
  /** Callback invoked when the user changes either date. */
  onChange: (range: DateRange) => void;
}

/** Default label shown when no date is selected. */
const EMPTY_LABEL = "All data";

/**
 * Renders a pair of date inputs with a label indicating the active range.
 *
 * @param props - The current range value and change callback.
 * @returns A styled date range picker element.
 */
export default function DateRangePicker({
  value,
  onChange,
}: DateRangePickerProps): React.JSX.Element {
  const handleFromChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      onChange({ ...value, from: e.target.value });
    },
    [value, onChange],
  );

  const handleToChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      onChange({ ...value, to: e.target.value });
    },
    [value, onChange],
  );

  const handleClear = useCallback(() => {
    onChange({ from: "", to: "" });
  }, [onChange]);

  const hasRange = value.from !== "" || value.to !== "";
  const rangeLabel = hasRange
    ? `${value.from || EMPTY_LABEL} — ${value.to || "now"}`
    : EMPTY_LABEL;

  return (
    <div className="flex flex-wrap items-end gap-4">
      <div>
        <label
          htmlFor="date-range-from"
          className="mb-1 block text-sm font-medium text-gray-700"
        >
          From
        </label>
        <input
          id="date-range-from"
          type="date"
          value={value.from}
          onChange={handleFromChange}
          className="rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-indigo-500 focus:outline-none focus:ring-indigo-500"
        />
      </div>
      <div>
        <label
          htmlFor="date-range-to"
          className="mb-1 block text-sm font-medium text-gray-700"
        >
          To
        </label>
        <input
          id="date-range-to"
          type="date"
          value={value.to}
          onChange={handleToChange}
          className="rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-indigo-500 focus:outline-none focus:ring-indigo-500"
        />
      </div>
      <span className="pb-2 text-sm text-gray-500">{rangeLabel}</span>
      {hasRange && (
        <button
          type="button"
          onClick={handleClear}
          className="rounded-md border border-gray-300 bg-white px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
        >
          Clear
        </button>
      )}
    </div>
  );
}
