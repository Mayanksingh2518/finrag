import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Dev server proxies /api to the FastAPI backend (uvicorn app.api.main:app --port 8010).
const apiTarget = process.env.FINRAG_API ?? 'http://127.0.0.1:8010'

export default defineConfig({
  plugins: [react()],
  server: { proxy: { '/api': { target: apiTarget, changeOrigin: true } } },
})
