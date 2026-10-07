// `vitest/config` rather than `vite`: it is the same helper with the `test`
// block typed, so the config stays in one file instead of growing a second one
// that has to be kept in sync.
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import path from 'node:path'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { '@': path.resolve(__dirname, './src') },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    // Co-located with the code they cover, same convention as the backend.
    include: ['src/**/*.test.{ts,tsx}'],
    // A jsdom run is not a browser: recharts cannot lay out an SVG, so chart
    // rendering is asserted through its data, never its pixels.
    coverage: {
      provider: 'v8',
      reporter: ['text', 'html'],
      include: ['src/**/*.{ts,tsx}'],
      exclude: ['src/**/*.test.{ts,tsx}', 'src/test/**', 'src/types/**', 'src/main.tsx'],
    },
  },
  server: {
    port: 5173,
    host: '127.0.0.1',
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      // The health probe lives outside the versioned API prefix, so it needs
      // its own proxy entry — otherwise the SPA fallback returns index.html and
      // the JSON consumer blows up on `res.data.llm`.
      '/health': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
    chunkSizeWarningLimit: 900,
    rollupOptions: {
      output: {
        manualChunks: {
          react: ['react', 'react-dom', 'react-router-dom'],
          charts: ['recharts'],
          vendor: ['axios', 'zustand', '@tanstack/react-query'],
        },
      },
    },
  },
})
