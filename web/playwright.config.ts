import { defineConfig, devices } from "@playwright/test";
import { mkdtempSync, mkdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
const webRoot = dirname(fileURLToPath(import.meta.url));
const root = resolve(webRoot, "..");
const scratch = process.env.TMPDIR || join(root, ".cache", "e2e");
mkdirSync(scratch, { recursive: true });
const stateRoot = mkdtempSync(join(scratch, "aegis-ui-e2e-"));
const runKey =
  new Date().toISOString().replace(/[:.]/g, "-") + "-" + process.pid;
const artifacts = join(
  root,
  ".hermes",
  "artifacts",
  "ui-01",
  "browser",
  runKey,
);
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 45_000,
  globalTimeout: 180_000,
  expect: { timeout: 7_000 },
  outputDir: join(artifacts, "test-results"),
  reporter: [
    ["list"],
    ["json", { outputFile: join(artifacts, "results.json") }],
  ],
  use: {
    baseURL: "http://127.0.0.1:5175",
    locale: "en-US",
    timezoneId: "Asia/Seoul",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "off",
  },
  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1440, height: 1000 },
      },
    },
  ],
  webServer: [
    // Bind failures stay fatal; stdout readiness avoids unbounded closed-port probes.
    // The suite verifies HTTP health after both owned processes have actually bound.
    {
      name: "aegis-api-e2e",
      command:
        ".venv/bin/python -m uvicorn aiddos.api.app:app --host 127.0.0.1 --port 5182",
      cwd: root,
      wait: { stderr: /Uvicorn running on http:\/\/127\.0\.0\.1:5182/ },
      env: { AIDDOS_UI_STATE_PATH: join(stateRoot, "drafts.json") },
      reuseExistingServer: false,
      timeout: 45_000,
      gracefulShutdown: { signal: "SIGTERM", timeout: 5_000 },
    },
    {
      name: "aegis-web-e2e",
      command: "npm run dev -- --port 5175",
      cwd: webRoot,
      wait: { stdout: /http:\/\/127\.0\.0\.1:5175/ },
      env: { VITE_API_PROXY_TARGET: "http://127.0.0.1:5182" },
      reuseExistingServer: false,
      timeout: 30_000,
      gracefulShutdown: { signal: "SIGTERM", timeout: 5_000 },
    },
  ],
});
