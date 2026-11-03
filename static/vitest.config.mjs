import { defineConfig } from 'vitest/config'
import { resolve } from 'path'

export default defineConfig({
  test: {
    environment: 'jsdom',
    include: ['**/*.test.mjs', '**/*.spec.mjs'],
    globals: true,
  },
  resolve: {
    alias: {
      '@': resolve(import.meta.dirname, '..', 'src'),
    },
  },
})