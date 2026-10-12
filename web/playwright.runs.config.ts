import { defineConfig, devices } from "@playwright/test";
import { lstatSync } from "node:fs";
import { isAbsolute, join } from "node:path";

// Explicit invocation bindings only. Collection never starts or adopts a server.
const origin = process.env.I3_WEB_ORIGIN;
const match = /^http:\/\/127\.0\.0\.1:([1-9][0-9]{0,4})$/.exec(origin ?? "");
if (!match || Number(match[1]) > 65535 || [5173, 5180].includes(Number(match[1]))) {
  throw new Error("explicit owned I3_WEB_ORIGIN required; active endpoints forbidden");
}
const output = process.env.I3_WEB_OUTPUT;
if (!output || !isAbsolute(output) || !lstatSync(output).isDirectory() || lstatSync(output).isSymbolicLink()) {
  throw new Error("explicit owned I3_WEB_OUTPUT directory required");
}

export default defineConfig({
  testDir: "./e2e",
  testMatch: "runs.spec.ts",
  grep: /real EN\/KO|exact-byte/,
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 30_000,
  expect: { timeout: 10_000 },
  outputDir: join(output, "test-results"),
  reporter: [
    ["list"],
    ["json", { outputFile: join(output, "results.json") }],
    ["junit", { outputFile: join(output, "junit.xml") }],
  ],
  use: {
    baseURL: origin,
    locale: "en-US",
    timezoneId: "Asia/Seoul",
    trace: "on",
    screenshot: "only-on-failure",
    video: "off",
    serviceWorkers: "block",
  },
  projects: [{ name: "chromium", use: {
    ...devices["Desktop Chrome"], viewport: { width: 1440, height: 1000 },
  } }],
});
