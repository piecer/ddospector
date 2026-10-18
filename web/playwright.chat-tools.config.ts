import { defineConfig, devices } from "@playwright/test";
import { resolve } from "node:path";

const dir = process.env.CHAT02A_DIR;
const mode = process.env.CHAT02A_MODE;
const base = process.env.CHAT02A_WEB;
if (!dir || !["fixture", "real"].includes(mode ?? "") || !base) {
  throw new Error(
    "Use tools/chat_tools_acceptance.py; unmanaged browser admission denied",
  );
}
const endpoint = new URL(base);
if (
  endpoint.hostname !== "127.0.0.1" ||
  ["5173", "5180", "11434"].includes(endpoint.port)
) {
  throw new Error("Only the invocation-owned source UI is permitted");
}
export default defineConfig({
  testDir: "./e2e",
  testMatch: "chat-tools.case.ts",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 800_000,
  globalTimeout: 840_000,
  expect: { timeout: 15_000 },
  outputDir: resolve(dir, "browser-results"),
  reporter: [
    ["list"],
    ["json", { outputFile: resolve(dir, "playwright.json") }],
  ],
  use: {
    baseURL: base,
    headless: true,
    locale: "ko-KR",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "off",
  },
  projects: [
    {
      name: "chat-tools-chromium",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 900, height: 1000 },
      },
    },
  ],
  // Python owns all processes, clocks and cleanup; no reused webServer, no route mocks.
});
