import { defineConfig, devices } from "@playwright/test";
import { LOCKED, OPEN, PASSWORD } from "./e2e/env";

// The real backend on synthetic demo data: one open server, one behind a password. Both serve
// web/dist, so `pnpm test:e2e` builds first. Specs share each server's database, so they run one
// at a time and clean up what they create.

export default defineConfig({
  testDir: "e2e",
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: OPEN,
    trace: "retain-on-failure",
    timezoneId: "UTC",
    locale: "en-US",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1400, height: 1000 } } }],
  webServer: [
    {
      command: "node e2e/server.mjs --port 8790",
      url: `${OPEN}/api/health`,
      reuseExistingServer: !process.env.CI,
      timeout: 180_000,
    },
    {
      command: `node e2e/server.mjs --port 8791 --password ${PASSWORD}`,
      url: `${LOCKED}/api/health`,
      reuseExistingServer: !process.env.CI,
      timeout: 180_000,
    },
  ],
});
