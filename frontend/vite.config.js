import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// base './' → el build funciona en cualquier ruta (raíz de un dominio, subcarpeta de GitHub Pages…).
// La navegación usa #/ruta, así que no hace falta configurar redirecciones en el hosting.
// En desarrollo, /api se redirige al backend FastAPI local.
export default defineConfig({
  plugins: [react()],
  base: './',
  server: {
    port: 5173,
    proxy: { '/api': 'http://127.0.0.1:8000' },
  },
})
