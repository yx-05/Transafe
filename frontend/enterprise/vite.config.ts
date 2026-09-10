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
    rollupOptions: {
      output: {
        // Split the heavy, rarely-changing libraries out of the app chunk. The
        // graph and chart renderers together are most of the bundle, and on a
        // booth machine the second load after a rebuild is the one that matters
        // — a single 740 kB chunk re-downloads all of it to pick up a one-line
        // change in the console shell.
        manualChunks: {
          "vendor-react": ["react", "react-dom", "react-router-dom"],
          "vendor-graph": ["react-force-graph-2d"],
          "vendor-charts": ["recharts"],
          "vendor-motion": ["framer-motion"],
        },
      },
    },
  },
});
