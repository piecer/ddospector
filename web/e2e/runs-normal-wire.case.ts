import { test, expect } from "@playwright/test";
import { createHash } from "node:crypto";
import { writeFileSync } from "node:fs";
import { decodeResponse } from "../src/pages/runs/client";
import { normalWireCases, normalWireRoot } from "../src/pages/runs/normalWireFixture";

test("recorded producer bytes have identical Node and Chromium decisions", async ({ page, context }, info) => {
  const denied: string[] = [];
  await context.routeWebSocket("**/*", socket => socket.close());
  await context.route("**/*", async route => {
    const request = route.request(), url = new URL(request.url());
    const allowed = url.pathname === "/e2e/fixtures/runs-normal-wire.html" ||
      /^\/(src\/|node_modules\/|@vite\/|@id\/)/.test(url.pathname) ||
      url.pathname.startsWith("/@fs" + normalWireRoot + "/runtime/vite/");
    if (url.origin === process.env.I3_WEB_ORIGIN && request.method() === "GET" && allowed)
      return route.continue();
    denied.push(request.method() + " " + request.url());
    await route.abort("blockedbyclient");
  });
  await page.goto("/e2e/fixtures/runs-normal-wire.html");
  const node = [];
  for (const row of normalWireCases) {
    const bytes = Buffer.from(row.raw, "utf8");
    let verdict = "ACCEPT";
    try { await decodeResponse(bytes, row.context); }
    catch (error) { verdict = error instanceof Error && error.message === "Invalid run response."
      ? "REJECT" : "UNEXPECTED_ERROR"; }
    node.push({ label: row.label, sha256: createHash("sha256").update(bytes).digest("hex"), verdict });
  }
  const chromium = await page.evaluate(async rows => {
    const path = "/src/pages/runs/client.ts";
    const { decodeResponse } = await import(/* @vite-ignore */ path);
    const results = [];
    for (const row of rows) {
      const bytes = new TextEncoder().encode(row.raw);
      const sha256 = [...new Uint8Array(await crypto.subtle.digest("SHA-256", bytes))]
        .map(n => n.toString(16).padStart(2, "0")).join("");
      let verdict = "ACCEPT";
      try { await decodeResponse(bytes, row.context); }
      catch (error) { verdict = error instanceof Error && error.message === "Invalid run response."
        ? "REJECT" : "UNEXPECTED_ERROR"; }
      results.push({ label: row.label, sha256, verdict });
    }
    return results;
  }, normalWireCases);
  writeFileSync(info.outputPath("normal-wire-parity.json"), JSON.stringify({
    scope: "Recorded normal HTTP replay plus labeled consumer negatives, not a new backend execution",
    node, chromium, denied,
  }, null, 2));
  expect(denied).toEqual([]);
  expect(node).toEqual(normalWireCases.map(row => ({
    label: row.label, sha256: row.sha256, verdict: row.expected,
  })));
  expect(chromium).toEqual(node);
});
