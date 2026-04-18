import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

const API_TARGET = process.env.APEX_SERVER_URL ?? "http://127.0.0.1:8765";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "./src") },
  },
  server: {
    port: 5173,
    // Proxy backend routes so the browser sees one origin — cookies and
    // SSE both need that to work cleanly without CORS gymnastics.
    proxy: {
      "/auth": { target: API_TARGET, changeOrigin: true },
      "/sessions": { target: API_TARGET, changeOrigin: true },
      "/health": { target: API_TARGET, changeOrigin: true },
    },
  },
});
