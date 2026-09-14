import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Dev: `npm run dev` serves the client on 5173 and proxies /api to the FastAPI
// bridge on 8765 (run_server.py). Prod: `npm run build` writes dist/, which the
// bridge serves itself, so one process answers everything.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: { '/api': { target: 'http://127.0.0.1:8765', changeOrigin: true } },
  },
  build: { outDir: 'dist', sourcemap: true, chunkSizeWarningLimit: 1200 },
})
