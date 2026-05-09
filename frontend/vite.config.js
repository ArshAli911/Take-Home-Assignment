import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// In dev, proxy `/api/*` to the FastAPI backend so the same relative
// URLs work in dev and in the nginx-served production build.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
});
