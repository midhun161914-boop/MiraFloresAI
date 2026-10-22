import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In dev, Vite serves the UI on :5173 and proxies /api to FastAPI on :8000.
// In production FastAPI serves the built files itself (same origin).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: { "/api": { target: `http://127.0.0.1:${process.env.API_PORT ?? "8000"}`, changeOrigin: true } },
  },
});
