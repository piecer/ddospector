import { defineConfig } from "@playwright/test";
import owned from "./playwright.runs.config";
if (!process.env.FOCUS_CHROMIUM) throw Error("explicit installed Chromium required");
export default defineConfig({
  ...owned,
  testMatch: "runs-focus.case.ts",
  grep: undefined,
  projects: [{ name: "chromium", use: {
    browserName: "chromium", headless: true,
    launchOptions: { executablePath: process.env.FOCUS_CHROMIUM },
    viewport: { width: 1440, height: 1000 },
  } }],
});
