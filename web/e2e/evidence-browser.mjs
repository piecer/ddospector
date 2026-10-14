import { chromium } from "playwright";
import assert from "node:assert/strict";
import { readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
const [baseURL, out, executablePath] = process.argv.slice(2);
assert(baseURL && out && executablePath);
const u = new URL(baseURL);
assert(u.hostname === "127.0.0.1" && !["5173", "5180"].includes(u.port));
const fixture = (name) =>
  readFileSync(resolve("tests/fixtures/evidence", name));
const registered = JSON.parse(fixture("complete-registered.body")),
  analyzed = JSON.parse(fixture("complete-detail.body")),
  run = JSON.parse(fixture("run-before.body"));
const canonical = (v) =>
  v === null || typeof v !== "object"
    ? JSON.stringify(v)
    : Array.isArray(v)
      ? "[" + v.map(canonical).join(",") + "]"
      : "{" +
        Object.keys(v)
          .sort()
          .map((k) => JSON.stringify(k) + ":" + canonical(v[k]))
          .join(",") +
        "}";
const browser = await chromium.launch({ executablePath, headless: true });
const errors = [],
  requests = [],
  coherence = [],
  downloads = [];
let posted = 0,
  getCount = 0,
  full = false,
  oversized = false;
try {
  const context = await browser.newContext({
    viewport: { width: 900, height: 1000 },
    acceptDownloads: true,
  });
  context.on("page", (page) => {
    page.on("pageerror", (e) => errors.push(String(e)));
    page.on("console", (m) => {
      if (m.type() === "error") errors.push(m.text());
    });
  });
  await context.addInitScript((id) => {
    crypto.randomUUID = () => id;
    window.__urls = { created: 0, retired: 0 };
    const create = URL.createObjectURL.bind(URL),
      revoke = URL.revokeObjectURL.bind(URL);
    URL.createObjectURL = (b) => {
      window.__urls.created++;
      return create(b);
    };
    URL.revokeObjectURL = (u) => {
      window.__urls.retired++;
      return revoke(u);
    };
  }, registered.evidence.request_id);
  // Controlled scheduling envelopes are explicitly projected from actual producer rows.
  // All selected detail/report responses are the exact retained producer API bytes.
  await context.route("**/*", async (route) => {
    const req = route.request(),
      url = new URL(req.url());
    assert(url.origin === u.origin, "external request forbidden");
    if (!url.pathname.startsWith("/api/")) return route.continue();
    requests.push({ method: req.method(), path: url.pathname });
    const send = (body, status = 200) =>
      route.fulfill({ status, contentType: "application/json", body });
    if (url.pathname === "/api/v1/offline-runs")
      return send(
        canonical({
          schema_version: 1,
          after: 0,
          through: 1,
          limit: 20,
          total: 1,
          items: [run.run],
          next_after: null,
        }),
      );
    if (url.pathname === `/api/v1/offline-runs/${run.run.id}`)
      return send(fixture("run-before.body"));
    if (url.pathname === "/api/v1/evidence" && req.method() === "POST") {
      const body = req.postDataJSON();
      assert.equal(body.request_id, registered.evidence.request_id);
      assert.equal(body.run_id, run.run.id);
      for (const side of ["ingress", "egress"]) {
        assert.equal(body[side].name, registered.evidence[side].name);
        assert.deepEqual(
          Buffer.from(body[side].base64, "base64"),
          readFileSync(`web/public/evidence-samples-v1/complete-${side}.pcap`),
        );
      }
      posted++;
      return send(fixture("complete-registered.body"), 201);
    }
    if (url.pathname === "/api/v1/evidence" && oversized)
      return send("x".repeat(65537));
    if (url.pathname === "/api/v1/evidence")
      return send(
        full
          ? fixture("full-list.body")
          : canonical({
              schema_version: 1,
              items: posted ? [registered.evidence] : [],
              total: posted ? 1 : 0,
            }),
      );
    if (url.pathname === `/api/v1/evidence/${registered.evidence.id}`) {
      getCount++;
      return send(fixture("complete-detail.body"));
    }
    if (
      url.pathname.startsWith(`/api/v1/evidence/${registered.evidence.id}/raw/`)
    ) {
      const side = url.pathname.split("/").at(-1);
      assert(["ingress", "egress"].includes(side));
      return route.fulfill({
        status: 200,
        contentType: "application/octet-stream",
        body: readFileSync(
          `web/public/evidence-samples-v1/complete-${side}.pcap`,
        ),
      });
    }
    throw Error("Unexpected API route " + req.method() + " " + url.pathname);
  });
  let page = await context.newPage();
  page.setDefaultTimeout(10000);
  await page.goto(baseURL + "/e2e/fixtures/evidence.html");
  await page
    .getByLabel("Completed OFFLINE Run", { exact: true })
    .selectOption(run.run.id);
  await page.getByLabel("Ingress PCAP", { exact: true }).focus();
  await page.keyboard.press("Tab");
  assert(
    await page
      .getByLabel("Egress PCAP", { exact: true })
      .evaluate((e) => document.activeElement === e),
  );
  await page
    .getByRole("button", { name: "Use sample pair in form", exact: true })
    .click();
  await page
    .getByText("complete-ingress.pcap · 1064 bytes", { exact: true })
    .waitFor();
  assert.equal(posted, 0);
  for (const side of ["ingress", "egress"])
    await page
      .getByLabel(side === "ingress" ? "Ingress PCAP" : "Egress PCAP", {
        exact: true,
      })
      .setInputFiles({
        name: registered.evidence[side].name,
        mimeType: "application/octet-stream",
        buffer: readFileSync(
          `web/public/evidence-samples-v1/complete-${side}.pcap`,
        ),
      });
  await page
    .getByRole("button", { name: "Register originals", exact: true })
    .click();
  await page
    .getByRole("heading", { name: "Registered · unassessed", exact: true })
    .waitFor();
  await page
    .getByRole("heading", {
      name: "SATISFIED · criterion satisfied",
      exact: true,
    })
    .waitFor();
  assert.equal(posted, 1);
  assert.equal(getCount, 1); // No Refresh or route priming.
  const assertCoherence = async (locale, width) => {
    // One DOM observation: repository row, selected terminal report and original
    // Run warning must agree together, before any Refresh or replacement route.
    const observed = await page.evaluate(
      ({ id, locale }) => {
        const choice = [...document.querySelectorAll(".evidence-choice")].find(
          (e) => e.textContent.includes(id),
        );
        const row = choice?.closest("li");
        const selected = document
          .querySelector(".evidence-page .chips")
          ?.closest("section");
        const state =
          locale === "ko"
            ? "단일 기준 결과 보관됨"
            : "Retained criterion result";
        const outcome =
          locale === "ko"
            ? "SATISFIED · 단일 기준 충족"
            : "SATISFIED · criterion satisfied";
        return {
          id,
          rowTerminal: !!row?.textContent.includes(state),
          selectedChoice: choice?.getAttribute("aria-pressed") === "true",
          selectedID: !!selected?.textContent.includes(id),
          selectedTerminal: !!selected
            ?.querySelector(".chips")
            ?.textContent.includes(state),
          outcome: !![...(selected?.querySelectorAll("h2") ?? [])].some(
            (e) => e.textContent === outcome,
          ),
          originalRunWarning: !!selected?.textContent.includes(
            "NOT_EVALUATED / defense_verdict: null",
          ),
          unassessedRow: !!row?.textContent.includes(
            locale === "ko" ? "등록됨 · 미평가" : "Registered · unassessed",
          ),
        };
      },
      { id: registered.evidence.id, locale },
    );
    assert.deepEqual(observed, {
      id: registered.evidence.id,
      rowTerminal: true,
      selectedChoice: true,
      selectedID: true,
      selectedTerminal: true,
      outcome: true,
      originalRunWarning: true,
      unassessedRow: false,
    });
    coherence.push({ locale, width, ...observed });
  };
  await assertCoherence("en", 900);
  const parity = [];
  for (const name of [
    "complete-detail.body",
    "violation-detail.body",
    "unknown-detail.body",
    "complete-registered.body",
  ]) {
    const raw = Array.from(fixture(name));
    const result = await page.evaluate(async (raw) => {
      const { decodeDetail } = await import("/src/pages/evidence/codec.ts");
      const d = await decodeDetail(new Uint8Array(raw));
      return { outcome: d.report?.outcome ?? null, id: d.evidence.id };
    }, raw);
    parity.push({ name, ...result });
  }
  const negative = fixture("complete-detail.body")
    .toString()
    .replace('"ordinal":1', '"ordinal":1.0');
  assert.equal(
    await page.evaluate(async (raw) => {
      const { decodeDetail } = await import("/src/pages/evidence/codec.ts");
      try {
        await decodeDetail(new TextEncoder().encode(raw));
        return false;
      } catch {
        return true;
      }
    }, negative),
    true,
  );
  const geometry = async () =>
    page.evaluate(() => ({
      width: innerWidth,
      scroll: document.documentElement.scrollWidth,
      overflow: [
        ...document.querySelectorAll(
          ".evidence-page button,.evidence-page input,.evidence-page select,.evidence-facts dd",
        ),
      ]
        .filter((e) => {
          const r = e.getBoundingClientRect();
          return r.width && (r.left < 0 || r.right > innerWidth + 1);
        })
        .map((e) => e.tagName + ":" + e.textContent?.slice(0, 100)),
    }));
  for (const locale of ["en", "ko"]) {
    if (locale === "ko")
      await page.locator(".language-control select").selectOption("ko");
    for (const width of [900, 390]) {
      await page.setViewportSize({ width, height: 1000 });
      await page
        .getByRole("heading", {
          name:
            locale === "ko"
              ? "SATISFIED · 단일 기준 충족"
              : "SATISFIED · criterion satisfied",
          exact: true,
        })
        .scrollIntoViewIfNeeded();
      const g = await geometry();
      await assertCoherence(locale, width);
      assert(g.scroll <= g.width + 1, JSON.stringify(g));
      assert.deepEqual(g.overflow, []);
      writeFileSync(
        `${out}/geometry-${locale}-${width}.json`,
        JSON.stringify(g, null, 2),
      );
      await page.screenshot({ path: `${out}/evidence-${locale}-${width}.png` });
    }
    writeFileSync(
      `${out}/accessibility-${locale}.txt`,
      await page.locator(".evidence-page").ariaSnapshot(),
    );
    for (const format of ["JSON", "HTML"]) {
      const event = page.waitForEvent("download");
      await page
        .getByRole("button", {
          name: locale === "ko" ? `${format} 내보내기` : `Export ${format}`,
          exact: true,
        })
        .click();
      const d = await event;
      const path = `${out}/${locale}.${format.toLowerCase()}`;
      await d.saveAs(path);
      downloads.push({ locale, format, filename: d.suggestedFilename() });
    }
  }
  assert.deepEqual(
    readFileSync(`${out}/en.json`),
    readFileSync(`${out}/ko.json`),
  );
  const rawEvent = page.waitForEvent("download");
  await page
    .getByRole("button", { name: "유입 원본 다운로드", exact: true })
    .click();
  const raw = await rawEvent;
  await raw.saveAs(`${out}/original-ingress.pcap`);
  assert.deepEqual(
    readFileSync(`${out}/original-ingress.pcap`),
    readFileSync("web/public/evidence-samples-v1/complete-ingress.pcap"),
  );
  // This retained full-list fixture is from a DIFFERENT repository/Run. Use a
  // fresh controller in a second page instead of pretending its ordinal-1 ID
  // replaces the selected immutable bundle. Keep its actual bytes/assertions.
  const selectedPage = page;
  full = true;
  page = await context.newPage();
  page.setDefaultTimeout(10000);
  await page.goto(baseURL + "/e2e/fixtures/evidence.html");
  await page.locator(".language-control select").selectOption("ko");
  await page
    .getByRole("button", { name: "저장소 새로고침", exact: true })
    .click();
  await page.getByRole("button", { name: /^#16 / }).waitFor();
  const choices = page.getByRole("button", { name: /^#\d+ / });
  assert.equal(await choices.count(), 16);
  await choices.last().focus();
  assert.equal(
    await choices.last().evaluate((e) => document.activeElement === e),
    true,
  );
  oversized = true;
  await page
    .getByRole("button", { name: "저장소 새로고침", exact: true })
    .click();
  await page
    .getByText("오래된 저장소 스냅샷 · 16/16", { exact: true })
    .waitFor();
  assert.equal(await choices.count(), 16);
  await page.close();
  page = selectedPage;
  await page
    .getByRole("button", { name: "Unmount fixture", exact: true })
    .click();
  await page.waitForTimeout(1100);
  const urls = await page.evaluate(() => window.__urls);
  assert.equal(urls.created, urls.retired);
  assert.deepEqual(errors, []);
  writeFileSync(
    `${out}/browser-result.json`,
    JSON.stringify(
      {
        scope: "CONTROLLED_HTTP_FIXTURE_NOT_LIVE_ACCEPTANCE",
        posted,
        getCount,
        coherence,
        parity,
        requests,
        downloads,
        urls,
        errors,
      },
      null,
      2,
    ),
  );
  await context.close();
  const staticContext = await browser.newContext({ javaScriptEnabled: false });
  const external = [];
  await staticContext.route("**/*", (route) => {
    const url = new URL(route.request().url());
    if (url.protocol === "file:") return route.continue();
    external.push(url.href);
    return route.abort();
  });
  const staticPage = await staticContext.newPage();
  for (const locale of ["en", "ko"]) {
    await staticPage.goto("file://" + out + "/" + locale + ".html");
    assert.equal(await staticPage.locator("script").count(), 0);
    await staticPage
      .getByRole("heading", {
        name:
          locale === "ko"
            ? "SATISFIED · 단일 기준 충족"
            : "SATISFIED · criterion satisfied",
        exact: true,
      })
      .waitFor();
    await staticPage.screenshot({ path: `${out}/export-${locale}.png` });
  }
  assert.deepEqual(external, []);
  await staticContext.close();
} finally {
  await browser.close();
}
