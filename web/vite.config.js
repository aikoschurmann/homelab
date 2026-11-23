import { defineConfig } from 'vite'
import { svelte } from '@sveltejs/vite-plugin-svelte'

// https://vite.dev/config/
export default defineConfig({
  plugins: [svelte()],
  base: '/static/',
  build: {
    // the Flask server serves this folder; old builds are cleared (index.html is no-store)
    outDir: '../server/static',
    emptyOutDir: true,
    target: 'es2022',   // main.js awaits /api/server before importing the app
    rollupOptions: {
      output: {
        // content-hashed names: index.html (served no-store) always points at the current build
        entryFileNames: `assets/[name]-[hash].js`,
        chunkFileNames: `assets/[name]-[hash].js`,
        assetFileNames: `assets/[name]-[hash].[ext]`
      }
    }
  }
})
