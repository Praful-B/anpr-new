/**
 * @module App
 * Root application component — defines the route tree for the RAKSHAK
 * dashboard and wraps it with the AuthProvider and ToastProvider.
 * Manages WebSocket lifecycle for COP/ADMIN users.
 */

import React, { useEffect } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider, useAuth } from "./lib/auth";
import { wsClient, type WsMessage } from "./lib/ws";
import { ToastProvider, useToast } from "./components/Toast";
import ProtectedRoute from "./components/ProtectedRoute";

import Login from "./pages/Login";
import Register from "./pages/Register";
import CitizenComplaint from "./pages/CitizenComplaint";
import PoliceHotlist from "./pages/PoliceHotlist";
import PoliceVehicleDetail from "./pages/PoliceVehicleDetail";
import PoliceAnalytics from "./pages/PoliceAnalytics";
import AdminPanel from "./pages/AdminPanel";
import NotFound from "./pages/NotFound";

/**
 * Manages the WebSocket connection lifecycle for authenticated COP/ADMIN users.
 * Connects on mount when authenticated, disconnects on logout or unmount.
 * Subscribes to WS events and fires toast notifications for new sightings
 * and hotlist changes.
 */
function WsManager(): React.JSX.Element | null {
  const { isAuthenticated, user } = useAuth();
  const { addToast } = useToast();

  useEffect(() => {
    if (isAuthenticated && user && (user.role === "COP" || user.role === "ADMIN")) {
      wsClient.connect();

      const unsubscribe = wsClient.subscribe((message: WsMessage) => {
        if (message.type === "new_sighting" && message.data) {
          const sighting = message.data as Record<string, unknown>;
          const plate = (sighting.plate as string) ?? "Unknown";
          const confidence = (sighting.confidence as number) ?? 0;
          addToast(
            "New Sighting Detected",
            `Plate ${plate} — confidence ${confidence}%`,
            "warning",
          );
        }

        if (message.type === "hotlist_change" && message.data) {
          const change = message.data as Record<string, unknown>;
          const plate = (change.plate as string) ?? "Unknown";
          const status = (change.status as string)?.replace(/_/g, " ") ?? "Updated";
          addToast("Hotlist Updated", `Plate ${plate} → ${status}`, "info");
        }
      });

      return () => {
        unsubscribe();
        wsClient.disconnect();
      };
    }
    wsClient.disconnect();
    return undefined;
  }, [isAuthenticated, user, addToast]);

  return null;
}

/**
 * Top-level application shell — auth provider + toast provider + routing.
 */
export default function App(): React.JSX.Element {
  return (
    <AuthProvider>
      <ToastProvider>
        <WsManager />
        <BrowserRouter>
          <Routes>
            {/* Public routes */}
            <Route path="/login" element={<Login />} />
            <Route path="/register" element={<Register />} />

            {/* Citizen/Volunteer routes */}
            <Route element={<ProtectedRoute allowedRoles={["CITIZEN", "VOLUNTEER"]} />}>
              <Route path="/citizen" element={<CitizenComplaint />} />
            </Route>

            {/* Police routes (COP + ADMIN) */}
            <Route element={<ProtectedRoute allowedRoles={["COP", "ADMIN"]} />}>
              <Route path="/police" element={<PoliceHotlist />} />
              <Route path="/police/vehicle/:id" element={<PoliceVehicleDetail />} />
            </Route>

            {/* Analytics routes (COP + ADMIN) */}
            <Route element={<ProtectedRoute allowedRoles={["COP", "ADMIN"]} />}>
              <Route path="/analytics" element={<PoliceAnalytics />} />
            </Route>

            {/* Admin-only routes */}
            <Route element={<ProtectedRoute allowedRoles={["ADMIN"]} />}>
              <Route path="/admin" element={<AdminPanel />} />
            </Route>

            {/* Root redirect and 404 */}
            <Route path="/" element={<Navigate to="/login" replace />} />
            <Route path="*" element={<NotFound />} />
          </Routes>
        </BrowserRouter>
      </ToastProvider>
    </AuthProvider>
  );
}
