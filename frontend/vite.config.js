import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/ask': 'http://localhost:8080',
      '/ingest': 'http://localhost:8080',
      '/image': 'http://localhost:8080',
      '/annotations': 'http://localhost:8080',
      '/explain-step': 'http://localhost:8080',
      '/health': 'http://localhost:8080',
    },
  },
})
