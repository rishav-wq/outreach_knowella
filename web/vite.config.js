import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Proxy /api to the FastAPI backend so the frontend just fetches relative URLs.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // 127.0.0.1 (not localhost) so the proxy hits uvicorn's IPv4 bind on Windows
    proxy: { '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true } },
  },
})
