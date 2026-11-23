import { defineConfig } from 'vite'
import { svelte } from '@sveltejs/vite-plugin-svelte'

// https://vite.dev/config/
export default defineConfig({
  plugins: [svelte()],
  base: '/static/',
  build: {
    outDir: '../Homelab-Dashboard/static',
    emptyOutDir: false,
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
