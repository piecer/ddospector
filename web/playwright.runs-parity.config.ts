import { defineConfig } from "@playwright/test";
import owned from "./playwright.runs-focus.config";

// Dedicated .case.ts discovery; not part of the ordinary API/UI server suite.
export default defineConfig({ ...owned, testMatch: "runs-normal-wire.case.ts" });
