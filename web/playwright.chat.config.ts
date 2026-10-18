import { defineConfig, devices } from "@playwright/test";
import { resolve } from "node:path";

const artifacts = process.env.CHAT_ACCEPTANCE_DIR;
const mode = process.env.CHAT_ACCEPTANCE_MODE;
if (!artifacts || !["real", "fixture"].includes(mode ?? "")) {
  throw new Error(
    "Run tools/chat_acceptance.py; direct unmanaged browser execution is denied",
  );
}
export default defineConfig({
  testDir: "./e2e",
  testMatch: "chat-real-model.case.ts",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 840_000,
  globalTimeout: 870_000,
  expect: { timeout: 10_000 },
  outputDir: resolve(artifacts, "browser-results"),
  reporter: [
    ["list"],
    ["json", { outputFile: resolve(artifacts, "playwright.json") }],
  ],
  use: {
    baseURL: "http://127.0.0.1:5175",
    locale: "ko-KR",
    headless: true,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "off",
  },
  projects: [
    {
      name: "chat-chromium",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 900, height: 1000 },
      },
    },
  ],
  // Python owns API/Vite PIDs, starttimes, deadlines, restart and cleanup.
  // No Playwright webServer reuse and no page.route/fulfill in this suite.
});
