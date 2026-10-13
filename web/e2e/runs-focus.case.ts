import { test as base, expect, type Page } from "@playwright/test";
import { createHash } from "node:crypto";
import { readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { literalGeometry } from "./runs-geometry";
const root = resolve(import.meta.dirname, "../.."), ep = "/api/v1/offline-runs";
const directory = resolve(root, "tests/fixtures/runs/h1");
const index = JSON.parse(readFileSync(resolve(directory, "selected-index.json"), "utf8"));
const witness = index.find((r: { state: string; method: string; path: string }) => r.state === "SUCCEEDED" && r.method === "GET" && !r.path.includes("by-request"));
const bytes = readFileSync(resolve(directory, witness.body));
expect(createHash("sha256").update(bytes).digest("hex")).toBe(witness.sha256);
const detail = JSON.parse(bytes.toString("utf8"));
const eventRows = index.filter((r: { path: string; status: number }) => r.path.startsWith(witness.path + "/events?") && r.path.includes("limit=3") && r.status === 200);
const items = eventRows.flatMap((r: { body: string; sha256: string }) => {
  const b = readFileSync(resolve(directory, r.body));
  expect(createHash("sha256").update(b).digest("hex")).toBe(r.sha256);
  return JSON.parse(b.toString("utf8")).items;
});
const test = base.extend<{ denyNetwork: void }>({
  denyNetwork: [async ({ context }, use, info) => {
    const denied: string[] = [], requests: { method: string; path: string }[] = [];
    await context.route("**/*", async route => {
      const r = route.request(), u = new URL(r.url());
      requests.push({ method: r.method(), path: u.pathname });
      if (u.origin === process.env.I3_WEB_ORIGIN && r.method() === "GET" && !u.pathname.startsWith("/api/") && (/^\/(e2e\/|src\/|node_modules\/|@vite\/|@id\/)/.test(u.pathname) || u.pathname.startsWith("/@fs" + root + "/runtime/vite/"))) return route.continue();
      denied.push(r.method() + " " + r.url());
      await route.abort("blockedbyclient");
    });
    await context.routeWebSocket("**/*", socket => socket.close());
    try { await use(); } finally {
      writeFileSync(info.outputPath("network.json"), JSON.stringify({ denied, requests }, null, 2));
      expect(denied).toEqual([]);
    }
  }, { auto: true }],
});
function barrier() {
  let release!: () => void;
  const promise = new Promise<void>(r => { release = r; });
  return { promise, release };
}
async function controlled(page: Page, locale = "en") {
  let calls = 0, hold = false, fail = false;
  const arrived = barrier(), released = barrier(), served = barrier();
  const requests: string[] = [];
  await page.route("**/api/**", async route => {
    const r = route.request(), u = new URL(r.url());
    if (u.origin !== process.env.I3_WEB_ORIGIN || r.method() !== "GET") return route.fallback();
    requests.push(r.method() + " " + u.pathname + u.search);
    if (u.pathname === ep + "/" + detail.run.id) {
      calls++;
      if (hold) { arrived.release(); await released.promise; }
      await route.fulfill(fail ? { status: 503, json: { code: "RUN_DB_UNAVAILABLE", message: "Offline run storage is unavailable." } } : { status: 200, contentType: "application/json", body: bytes });
      if (hold) served.release();
      return;
    }
    if (u.pathname === ep) return route.fulfill({ json: { schema_version: 1, after: 0, through: 1, limit: 20, total: 1, items: [detail.run], next_after: null } });
    if (u.pathname === ep + "/" + detail.run.id + "/events") return route.fulfill({ json: { schema_version: 1, run_id: detail.run.id, after: 0, limit: 16, total: items.length, items, next_after: null } });
    if (u.pathname === "/api/v1/scenarios") return route.fulfill({ json: { revision: 0, total: 0, offset: 0, limit: 20, items: [], execution_enabled: false } });
    return route.fallback();
  });
  await page.addInitScript(() => {
    const state = window as unknown as { focusLog: unknown[] };
    state.focusLog = [];
    const record = (kind: string, target?: EventTarget | null) => {
      const retry = [...document.querySelectorAll("button")].find(b => /^(Retry run read|실행 읽기 재시도)$/.test(b.textContent ?? ""));
      state.focusLog.push({ kind, at: performance.now(), target: target instanceof Element ? target.tagName + ":" + target.textContent?.slice(0, 60) : null,
        active: document.activeElement?.tagName + ":" + document.activeElement?.textContent?.slice(0, 60),
        focused: retry === document.activeElement, disabled: retry?.disabled, ariaDisabled: retry?.getAttribute("aria-disabled"), connected: retry?.isConnected });
    };
    for (const type of ["focusin", "focusout", "keydown", "keyup"]) document.addEventListener(type, e => record(type, e.target), true);
    new MutationObserver(m => { if (m.some(x => ["disabled", "aria-disabled"].includes(x.attributeName ?? ""))) record("busy-attribute"); }).observe(document, { subtree: true, attributes: true, attributeFilter: ["disabled", "aria-disabled"] });
  });
  await page.goto(`/e2e/fixtures/runs-focus.html?locale=${locale}`);
  const run = page.getByRole("button", { name: detail.run.id, exact: true });
  await run.click();
  await expect(page.locator(".runs-summary")).toContainText("SUCCEEDED");
  await expect(page.locator(".runs-timeline li")).toHaveCount(items.length);
  return { calls: () => calls, requests, arrived, released, served,
    hold: (failure = false) => { hold = true; fail = failure; }, run };
}
async function capture(page: Page) {
  return page.evaluate(() => (window as unknown as { focusLog: unknown[] }).focusLog);
}
for (const locale of ["en", "ko"] as const) for (const width of [1440, 1024, 390]) {
  test(`UI-FOCUS retained exact GET and duplicate guard ${locale} ${width}`, async ({ page }, info) => {
    await page.setViewportSize({ width, height: 1000 });
    const h = await controlled(page, locale), retry = page.getByRole("button", { name: locale === "en" ? "Retry run read" : "실행 읽기 재시도", exact: true });
    const before = h.calls();
    const original = await retry.elementHandle();
    h.hold();
    try {
      await retry.focus(); await expect(retry).toBeFocused();
      await page.keyboard.press("Enter"); await h.arrived.promise;
      await expect(retry).toBeDisabled(); // native disabled OR accessible aria-disabled
      // Observe native rendering with no second input or imperative focus call.
      await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => {
        const state = window as unknown as { focusLog: unknown[] };
        state.focusLog.push({ kind: "before-duplicate-input", at: performance.now(), active: document.activeElement?.tagName + ":" + document.activeElement?.textContent?.slice(0, 60) });
        resolve();
      }))));
      await page.keyboard.press("Enter"); await page.keyboard.press("Space");
      const box = (await retry.boundingBox())!;
      await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
      expect(h.calls()).toBe(before + 1);
      const response = page.waitForResponse(r => r.url() === process.env.I3_WEB_ORIGIN + ep + "/" + detail.run.id && r.request().method() === "GET");
      h.released.release(); const completed = await response; await h.served.promise;
      expect(completed.status()).toBe(200); expect(await completed.body()).toEqual(bytes);
      await expect(retry).toBeEnabled();
      expect(await retry.evaluate((e, first) => e === first, original)).toBe(true);
      await expect(page.locator(".runs-timeline li")).toHaveCount(items.length);
      expect(h.calls()).toBe(before + 1);
      await expect(retry).toBeFocused();
      expect(await retry.evaluate(e => (e as HTMLButtonElement).disabled)).toBe(false);
    } finally {
      h.released.release();
      writeFileSync(info.outputPath("focus.json"), JSON.stringify({ provenance: "CONTROLLED_HTTP_REPLAY_NOT_BACKEND_ACCEPTANCE", witness, requests: h.requests, calls: h.calls(), timeline: await capture(page) }, null, 2));
    }
  });
}
for (const action of ["tab", "close", "unmount"] as const) for (const failure of [false, true]) {
  test(`UI-FOCUS late ${failure ? "failure" : "success"} respects ${action}`, async ({ page }, info) => {
    const h = await controlled(page), retry = page.getByRole("button", { name: "Retry run read", exact: true });
    h.hold(failure);
    try {
      await retry.focus(); await page.keyboard.press("Enter"); await h.arrived.promise;
      if (action === "tab") {
        await page.keyboard.press("Tab");
        await expect(page.getByRole("button", { name: "Reload events", exact: true })).toBeFocused();
      } else if (action === "close") {
        await page.getByRole("button", { name: "Close details", exact: true }).focus();
        await page.keyboard.press("Enter"); await expect(h.run).toBeFocused();
      } else {
        await page.getByRole("button", { name: "Unmount fixture", exact: true }).focus();
        await page.keyboard.press("Enter");
      }
      const destination = await page.evaluateHandle(() => document.activeElement);
      h.released.release(); await h.served.promise;
      if (action === "tab") {
        await expect(retry).toBeEnabled();
        if (failure) await expect(page.getByText(/Last verified data retained/)).toBeVisible();
      }
      expect(await page.evaluate(target => document.activeElement === target, destination)).toBe(true);
      expect(h.calls()).toBe(2);
      if (action !== "tab") await expect(retry).toHaveCount(0);
    } finally {
      h.released.release();
      writeFileSync(info.outputPath("late-focus.json"), JSON.stringify({ requests: h.requests, timeline: await capture(page) }, null, 2));
    }
  });
}

for (const mode of ["nested-scroll", "permanent-clip", "keyboard-blocked"] as const) {
  test(`UI-ORACLE ${mode} controlled geometry`, async ({ page }, info) => {
    const literal = "0123456789abcdef".repeat(4);
    await page.setContent(`<div style="width:140px;overflow:hidden"><div id="scroll" tabindex="0" style="width:140px;overflow:auto"><span id="literal" style="font:16px monospace;white-space:nowrap;${mode === "permanent-clip" ? "display:block;width:140px;overflow:hidden" : ""}">${literal}</span></div></div>`);
    if (mode === "keyboard-blocked") await page.locator("#scroll").evaluate(e => e.addEventListener("keydown", event => event.preventDefault()));
    const geometry = await literalGeometry(page.locator("#literal"), literal);
    writeFileSync(info.outputPath("geometry.json"), JSON.stringify(geometry, null, 2));
    if (mode === "nested-scroll") {
      expect(geometry.inaccessible).toEqual([]);
      expect(geometry.covered).toHaveLength(64);
      expect(geometry.moves.some(m => m.after > m.before)).toBe(true);
    } else expect(geometry.inaccessible.length).toBeGreaterThan(0);
  });
}

for (const locale of ["en", "ko"]) for (const width of [1440, 1024, 390]) {
  test(`UI-ORACLE shipped literals ${locale} ${width}`, async ({ page }, info) => {
    await page.setViewportSize({ width, height: 1000 });
    const h = await controlled(page, locale);
    const details = page.locator(".panel").filter({ has: page.getByRole("heading", { name: locale === "en" ? "Run details" : "실행 상세", exact: true }) });
    await details.locator("summary").filter({ hasText: locale === "en" ? "Captured scenario and declared limits" : "캡처 시나리오와 선언된 제한" }).click();
    const literals = [
      [h.run, detail.run.id],
      [details.locator("p.runs-identity").filter({ hasText: detail.run.id }), detail.run.id],
      [details.locator("dd").filter({ hasText: detail.snapshot.digest }), detail.snapshot.digest],
      [details.locator(".scenario-record dd").filter({ hasText: detail.snapshot.scenario.digest }), detail.snapshot.scenario.digest],
      [details.locator("p.runs-identity").filter({ hasText: detail.result.digest }), detail.result.digest],
    ] as const;
    const values = [];
    try {
      for (const [locator, literal] of literals) {
        const g = await literalGeometry(locator, literal);
        values.push(g);
        expect(g.inaccessible).toEqual([]);
        expect(g.documentWidth).toBeLessThanOrEqual(g.viewportWidth);
      }
    } finally { writeFileSync(info.outputPath("literals.json"), JSON.stringify(values, null, 2)); }
  });
}
