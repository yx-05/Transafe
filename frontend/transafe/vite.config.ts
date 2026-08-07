import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    allowedHosts: true,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      // Only the admin API prefix is proxied. The bare `/admin` and
      // `/admin/case/:id` routes must be served by the React SPA (they
      // previously 404'd because a broad `/admin` proxy shadowed them).
      // Over a Cloudflare tunnel the frontend's baseUrl equals the tunnel
      // origin, so these API calls arrive here and need forwarding.
      '/admin/v1': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/ws': {
        target: 'ws://127.0.0.1:8000',
        ws: true,
        changeOrigin: true,
      },
    },
  },
})
