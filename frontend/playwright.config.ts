import { defineConfig, devices } from '@playwright/test'

const enabled = process.env.PLAYWRIGHT_E2E_ENABLED === '1'
const baseURL =
  process.env.PLAYWRIGHT_BASE_URL || 'http://crm.localhost:8000/crm/'
const expectedSite = process.env.PLAYWRIGHT_EXPECTED_SITE || 'crm.localhost'
const allowedHost =
  process.env.PLAYWRIGHT_ALLOWED_HOST || new URL(baseURL).hostname
const runId = process.env.E2E_RUN_ID

if (enabled) {
  const url = new URL(baseURL)
  if (url.hostname !== allowedHost) {
    throw new Error(
      `Refusing Playwright mutations against ${url.hostname}; expected ${allowedHost}.`,
    )
  }
  if (!['http:', 'https:'].includes(url.protocol)) {
    throw new Error(`Unsupported Playwright base URL protocol: ${url.protocol}`)
  }
  if (!runId || !/^[A-Za-z0-9][A-Za-z0-9_-]{5,63}$/.test(runId)) {
    throw new Error('E2E_RUN_ID is required for guarded Playwright runs.')
  }
}

export default defineConfig({
  testDir: './tests/e2e',
  outputDir: 'test-results',
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI
    ? [['line'], ['html', { outputFolder: 'playwright-report', open: 'never' }]]
    : [
        ['list'],
        ['html', { outputFolder: 'playwright-report', open: 'never' }],
      ],
  use: {
    ...devices['Desktop Chrome'],
    baseURL,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    locale: process.env.PLAYWRIGHT_LOCALE || 'en-US',
    actionTimeout: 10_000,
    navigationTimeout: 30_000,
  },
  projects: [
    {
      name: 'setup',
      testMatch: /auth\.setup\.ts/,
      use: {
        ...devices['Desktop Chrome'],
        baseURL,
        trace: 'off',
        screenshot: 'off',
        video: 'off',
      },
    },
    {
      name: 'chromium',
      use: {
        ...devices['Desktop Chrome'],
        baseURL,
        storageState: 'playwright/.auth/sale.json',
        locale: process.env.PLAYWRIGHT_LOCALE || 'en-US',
      },
      dependencies: ['setup'],
    },
  ],
  metadata: {
    expectedSite,
    mutationGuard: enabled ? 'enabled' : 'disabled',
    runId: runId || 'none',
  },
})
