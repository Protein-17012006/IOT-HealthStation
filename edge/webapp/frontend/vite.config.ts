import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Built assets use relative paths so Flask can serve dist/ from the app root.
// In dev, /api is proxied to the Flask server on :5000.
export default defineConfig({
  plugins: [react()],
  base: './',
  build: { outDir: 'dist', emptyOutDir: true },
  server: {
    proxy: {
      '/api': { target: 'http://localhost:5000', changeOrigin: true },
    },
  },
})
