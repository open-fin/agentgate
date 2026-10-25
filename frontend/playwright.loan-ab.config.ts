import { defineConfig } from '@playwright/test';
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

// Never reuse a running user service or database for these mutation tests.
const directory =
  process.env.AGENTGATE_LOAN_AB_TEST_DIR || mkdtempSync(join(tmpdir(), 'agentgate-loan-ab-'));
process.env.AGENTGATE_LOAN_AB_TEST_DIR = directory;
const apiPort = Number(process.env.AGENTGATE_LOAN_AB_TEST_API_PORT || 8181);
const frontendPort = Number(process.env.AGENTGATE_LOAN_AB_TEST_FRONTEND_PORT || 5301);
const apiOrigin = `http://127.0.0.1:${apiPort}`;
const frontendOrigin = `http://127.0.0.1:${frontendPort}`;

export default defineConfig({
  testDir: './tests',
  testMatch: 'loan-ab-versions.spec.ts',
  timeout: 60_000,
  expect: { timeout: 10_000 },
  workers: 1,
  use: {
    baseURL: frontendOrigin,
    actionTimeout: 10000,
    viewport: { width: 1440, height: 1000 },
    launchOptions: { executablePath: process.env.PLAYWRIGHT_CHROME_PATH || undefined },
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
  },
  outputDir: '../runtime/loan-ab-browser-tests',
  webServer: [
    {
      command: `${process.env.AGENTGATE_TEST_PYTHON || '.venv/bin/python'} -m uvicorn agentgate.server.app:app --host 127.0.0.1 --port ${apiPort}`,
      cwd: resolve(fileURLToPath(new URL('.', import.meta.url)), '..'),
      url: `${apiOrigin}/health`,
      reuseExistingServer: false,
      timeout: 60_000,
      env: {
        AGENTGATE_DB_TYPE: 'sqlite',
        AGENTGATE_DB: join(directory, 'evaluators.sqlite3'),
        AGENTGATE_LOG_PATH: join(directory, 'logs'),
        AGENT_TASK_DISPATCHER_TYPE: 'celery',
        AGENTGATE_JUDGE_PROVIDER_ID: 'browser-test',
        AGENTGATE_JUDGE_MODEL_ID: 'browser-test-judge',
        AGENTGATE_JUDGE_TRANSPORT: 'api',
        AGENTGATE_JUDGE_API_KEY: 'unused-browser-test-key',
        // Catalog and publication validation must not make model requests.
        AGENTGATE_JUDGE_BASE_URL: 'https://127.0.0.1:9/v1',
      },
    },
    {
      command: `npm run dev -- --port ${frontendPort}`,
      url: frontendOrigin,
      reuseExistingServer: false,
      timeout: 60_000,
      env: { API_PROXY_TARGET: apiOrigin, FRONTEND_PORT: String(frontendPort) },
    },
  ],
});
