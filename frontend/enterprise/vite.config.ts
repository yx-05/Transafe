import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Enterprise Console dev server.
// Port 5174 so it can run side-by-side with the v1 consumer app (5173).
// /enterprise is proxied to the FastAPI backend, WebSocket included.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5174,
    strictPort: false,
    proxy: {
      "/enterprise": {
        target: "http://localhost:8000",
        changeOrigin: true,
        ws: true,
      },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: true,
  },
});
