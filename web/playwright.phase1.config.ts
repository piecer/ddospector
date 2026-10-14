import { defineConfig, devices } from "@playwright/test";
import { lstatSync, readFileSync } from "node:fs";
import { isAbsolute, join } from "node:path";

// Dedicated opt-in collection; never starts, adopts, or repairs a server.
const workspace = process.env.P1_WORKSPACE;
const output = process.env.P1_OUTPUT;
if (!workspace || !output || !isAbsolute(workspace) || !isAbsolute(output) ||
    !lstatSync(output).isDirectory() || lstatSync(output).isSymbolicLink()) {
  throw new Error("explicit P1_WORKSPACE and existing owned P1_OUTPUT required");
}
const state = JSON.parse(readFileSync(join(workspace, "workspace.json"), "utf8"));
if (state.phase !== "RUNNING" || !/^http:\/\/127\.0\.0\.1:(5175|5182)$/.test(state.origin)) {
  throw new Error("live Phase-1 workspace binding required");
}
const proxy = JSON.parse(readFileSync(join(state.session, "proxy.json"), "utf8"));
if (proxy.origin !== state.origin) throw new Error("owned proxy binding mismatch");
export default defineConfig({
  testDir: "./e2e", testMatch: "phase1-offline.case.ts",
  workers: 1, fullyParallel: false, retries: 0, timeout: 120_000,
  expect: { timeout: 15_000 }, outputDir: join(output, "test-results"),
  reporter: [["list"], ["json", { outputFile: join(output, "results.json") }],
    ["junit", { outputFile: join(output, "junit.xml") }]],
  use: { baseURL: state.origin, locale: "en-US", timezoneId: "Asia/Seoul",
    trace: "on", screenshot: "only-on-failure", video: "off", serviceWorkers: "block" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"],
    viewport: { width: 1440, height: 1000 } } }],
});
