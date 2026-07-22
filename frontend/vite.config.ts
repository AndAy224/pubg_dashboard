import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      // The API and the tile pyramid both live behind /api, so one rule covers
      // both and the browser never learns the backend's origin.
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: false },
    },
  },
  build: {
    // Pixi is ~400 KB on its own and only the replay route needs it; keeping
    // it out of the entry chunk means the match list is not waiting on a
    // renderer it will never use.
    rollupOptions: {
      output: {
        // Function form: Rollup in Vite 8 types `manualChunks` as
        // ManualChunksFunction, so the object shorthand no longer type-checks.
        manualChunks(id: string) {
          if (id.includes('node_modules/pixi.js')) return 'pixi'
          if (id.includes('node_modules/recharts') || id.includes('node_modules/d3-'))
            return 'charts'
          return undefined
        },
      },
    },
    chunkSizeWarningLimit: 900,
  },
})
