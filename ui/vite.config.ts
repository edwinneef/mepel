import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  plugins: [react()],
  base: '/',
  build: {
    outDir: '../src/maplebot/static/workbench',
    emptyOutDir: true,
  },
  test: {
    environment: 'jsdom',
    clearMocks: true,
  },
});
