import { defineConfig, devices } from "@playwright/test";

/**
 * End-to-end tests run against the real stack (Next.js + FastAPI + worker + PostgreSQL +
 * DuckDB). Nothing is mocked. Start the services first (see README), then `npm run e2e`.
 */
export default defineConfig({
  testDir: "./e2e",
  timeout: 120_000,
  expect: { timeout: 20_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: process.env.FACET_WEB_URL ?? "http://localhost:3000",
    trace: "off",
    screenshot: "only-on-failure",
    acceptDownloads: true,
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } } }],
});
