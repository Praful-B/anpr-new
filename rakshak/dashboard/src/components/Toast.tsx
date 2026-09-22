/**
 * @module Toast
 * Toast notification system for the RAKSHAK dashboard.
 *
 * Provides a React context + provider that manages a queue of toast
 * notifications. Toasts auto-dismiss after a configurable duration.
 * Triggered by WebSocket events (new_sighting, hotlist_change).
 */

import React, {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  useRef,
} from "react";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** Default duration before a toast auto-dismisses (ms). */
const DEFAULT_DISMISS_MS = 6000;

/** Maximum number of toasts visible at once. */
const MAX_VISIBLE_TOASTS = 5;

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** Visual severity of a toast notification. */
export type ToastVariant = "info" | "success" | "warning" | "error";

/** Shape of a single toast notification. */
export interface Toast {
  readonly id: string;
  readonly title: string;
  readonly message?: string;
  readonly variant: ToastVariant;
  readonly createdAt: number;
}

/** Function to add a toast notification. */
export type AddToast = (title: string, message?: string, variant?: ToastVariant) => void;

/** Shape of the toast context exposed via useToast(). */
export interface ToastContextValue {
  addToast: AddToast;
  toasts: readonly Toast[];
  dismissToast: (id: string) => void;
}

// ---------------------------------------------------------------------------
// Context
// ---------------------------------------------------------------------------

const ToastContext = createContext<ToastContextValue | undefined>(undefined);

// ---------------------------------------------------------------------------
// Provider
// ---------------------------------------------------------------------------

interface ToastProviderProps {
  children: React.ReactNode;
}

/**
 * Manages a queue of toast notifications and exposes an `addToast` function.
 *
 * @param props - React props, expects `children`.
 */
export function ToastProvider({ children }: ToastProviderProps): React.JSX.Element {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const _counterRef = useRef(0);

  const dismissToast = useCallback((id: string): void => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const addToast = useCallback<AddToast>(
    (title: string, message?: string, variant: ToastVariant = "info"): void => {
      _counterRef.current += 1;
      const id = `toast-${_counterRef.current}-${Date.now()}`;
      const toast: Toast = { id, title, message, variant, createdAt: Date.now() };

      setToasts((prev) => {
        const next = [toast, ...prev];
        return next.slice(0, MAX_VISIBLE_TOASTS);
      });

      setTimeout(() => {
        dismissToast(id);
      }, DEFAULT_DISMISS_MS);
    },
    [dismissToast],
  );

  const value = useMemo<ToastContextValue>(
    () => ({ addToast, toasts, dismissToast }),
    [addToast, toasts, dismissToast],
  );

  return (
    <ToastContext.Provider value={value}>
      {children}
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />
    </ToastContext.Provider>
  );
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

/**
 * Hook to access the toast notification system.
 *
 * Must be used within a {@link ToastProvider} ancestor.
 *
 * @returns The current {@link ToastContextValue}.
 * @throws If used outside of a ToastProvider.
 */
export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) {
    throw new Error("useToast must be used within a ToastProvider");
  }
  return ctx;
}

// ---------------------------------------------------------------------------
// Toast Container (renders floating toasts)
// ---------------------------------------------------------------------------

/** Colour mapping for toast variants. */
const VARIANT_STYLES: Record<ToastVariant, string> = {
  info: "bg-blue-600 text-white",
  success: "bg-green-600 text-white",
  warning: "bg-amber-500 text-white",
  error: "bg-red-600 text-white",
};

interface ToastContainerProps {
  toasts: readonly Toast[];
  onDismiss: (id: string) => void;
}

/**
 * Renders a stack of floating toast notifications in the top-right corner.
 *
 * @param props - The list of active toasts and a dismiss handler.
 */
function ToastContainer({ toasts, onDismiss }: ToastContainerProps): React.JSX.Element {
  if (toasts.length === 0) {
    return <></>;
  }

  return (
    <div className="fixed right-4 top-4 z-50 flex flex-col gap-2">
      {toasts.map((toast) => (
        <div
          key={toast.id}
          className={`max-w-sm rounded-lg px-4 py-3 shadow-lg transition-all duration-300 ${VARIANT_STYLES[toast.variant]}`}
          role="alert"
        >
          <div className="flex items-start justify-between">
            <div className="min-w-0 flex-1">
              <p className="text-sm font-semibold">{toast.title}</p>
              {toast.message && (
                <p className="mt-1 text-xs opacity-90">{toast.message}</p>
              )}
            </div>
            <button
              onClick={() => onDismiss(toast.id)}
              className="ml-2 flex-shrink-0 rounded p-1 text-white opacity-70 hover:opacity-100"
              aria-label="Dismiss notification"
            >
              &#x2715;
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}
