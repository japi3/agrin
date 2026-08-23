import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      // Proxy the API in development so the browser sees one origin and SSE
      // is not subject to CORS preflight on every turn.
      '/api': { target: 'http://localhost:8099', changeOrigin: true },
    },
  },
})
