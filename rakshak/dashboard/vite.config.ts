/**
 * Vite configuration for the RAKSHAK dashboard.
 *
 * The dev server proxies `/api` and `/ws` to the backend so the app can use
 * relative `VITE_API_URL` values in both development and production. The
 * upstream host comes from `VITE_PROXY_TARGET` (see .env.example); inside
 * docker-compose it defaults to the `backend` service name.
 */

import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

/** Default upstream for the dev-server proxy when no env override is set. */
const DEFAULT_PROXY_TARGET = "http://backend:8000";

/** Development server port exposed by docker-compose and the Dockerfile. */
const DEV_SERVER_PORT = 5173;

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const proxyTarget = env.VITE_PROXY_TARGET || DEFAULT_PROXY_TARGET;

  return {
    plugins: [react()],
    server: {
      port: DEV_SERVER_PORT,
      host: true,
      proxy: {
        "/api": {
          target: proxyTarget,
          changeOrigin: true,
        },
        "/sightings": {
          target: proxyTarget,
          changeOrigin: true,
        },
        "/ws": {
          target: proxyTarget,
          changeOrigin: true,
          ws: true,
        },
      },
    },
  };
});
