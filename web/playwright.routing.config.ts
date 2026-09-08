import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './tests',
  testMatch: 'routing.spec.ts',
  webServer: {
    command: 'npm run dev -- --host 127.0.0.1 --port 15173',
    port: 15173,
    reuseExistingServer: false,
  },
  use: { baseURL: 'http://127.0.0.1:15173' },
  projects: [{ name: 'routing', use: { ...devices['Desktop Chrome'] } }],
})
