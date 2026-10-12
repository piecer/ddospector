import { test as baseTest, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { createHash, randomUUID } from "node:crypto";
import { appendFileSync, readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
const root = resolve(import.meta.dirname, "../..");
const output = process.env.I3_WEB_OUTPUT!;
const base = process.env.I3_WEB_ORIGIN!;
const ep = "/api/v1/offline-runs";
const test = baseTest.extend<{ ownedNetwork: void }>({
  ownedNetwork: [async ({ context }, use, info) => {
    const journal = resolve(output, `network-${info.testId}.jsonl`);
    const denied: string[] = [];
    const pending: Promise<void>[] = [];
    let serial = 0;
    const record = (value: unknown) => appendFileSync(journal, JSON.stringify(value) + "\n");
    record({ kind: "binding", origin: base, test: info.title,
      specSha256: createHash("sha256").update(readFileSync(import.meta.filename)).digest("hex") });
    context.on("request", (r) => record({ kind: "request", method: r.method(), url: r.url(), body: r.postData() }));
    context.on("requestfailed", (r) => record({ kind: "requestfailed", url: r.url(), failure: r.failure() }));
    context.on("page", (page) => page.on("pageerror", (error) => record({ kind: "pageerror", message: error.message })));
    context.on("response", (r) => {
      if (new URL(r.url()).pathname.startsWith("/api/")) {
        const file = `network-${info.testId}-${serial++}.body`;
        pending.push((async () => {
          try {
            const bytes = await r.body();
            writeFileSync(resolve(output, file), bytes);
            record({ kind: "response", url: r.url(), status: r.status(), headers: r.headers(), file,
              sha256: createHash("sha256").update(bytes).digest("hex") });
          } catch (error) {
            record({ kind: "body-unavailable", url: r.url(), message: String(error) });
          }
        })());
      }
    });
    await context.route("**/*", async (route) => {
      if (new URL(route.request().url()).origin !== base) {
        denied.push(route.request().url());
        record({ kind: "foreign-request-denied", url: route.request().url() });
        await route.abort("blockedbyclient");
      } else await route.continue();
    });
    await context.routeWebSocket("**/*", (route) => {
      if (new URL(route.url()).origin !== base.replace("http:", "ws:")) {
        denied.push(route.url());
        record({ kind: "foreign-websocket-denied", url: route.url() });
        route.close();
      } else route.connectToServer();
    });
    try { await use(); }
    finally {
      await Promise.all(pending);
      record({ kind: "finished", status: info.status, denied });
      expect(denied).toEqual([]);
    }
  }, { auto: true }],
});
const input = JSON.parse(
  readFileSync(resolve(root, "tests/fixtures/runs/h1/selected-index.json"), "utf8"),
);
const witness = input.find((r: { state: string }) => r.state === "QUEUED");
const original = JSON.parse(
  readFileSync(resolve(root, "tests/fixtures/runs/h1", witness.body), "utf8"),
);
test("real EN/KO browser → isolated API → private PG → separate worker; reload receipt and ordinary observer", async ({
  page,
  request,
}, info) => {
  const external: string[] = [];
  const posts: string[] = [];
  const responses: {
    path: string;
    status: number;
    sha256: string;
    file: string;
  }[] = [];
  const pending: Promise<void>[] = [];
  page.on("request", (r) => {
    if (new URL(r.url()).origin !== base) external.push(r.url());
    if (r.method() === "POST" && new URL(r.url()).pathname.startsWith(ep))
      posts.push(new URL(r.url()).pathname);
  });
  page.on("response", (r) => {
    if (new URL(r.url()).pathname.startsWith(ep))
      pending.push(
        (async () => {
          const bytes = await r.body().catch(() => null);
          if (bytes) {
            const file = `browser-${responses.length.toString().padStart(4, "0")}.body`;
            writeFileSync(resolve(output, file), bytes);
            responses.push({
              path: r.url(),
              status: r.status(),
              sha256: createHash("sha256").update(bytes).digest("hex"),
              file,
            });
          }
        })(),
      );
  });
  await page.goto("/runs");
  await expect(
    page.getByRole("heading", { name: "Run history" }),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: "Start run" })).toBeDisabled();
  await expect(page.getByText("No OFFLINE runs yet")).toBeVisible();
  const dut = await request.post("/api/v1/targets", {
    data: { name: "I3 DUT metadata", address: "192.0.2.61", kind: "DUT" },
  });
  expect(dut.status()).toBe(201);
  const sink = await request.post("/api/v1/targets", {
    data: { name: "I3 SINK metadata", address: "192.0.2.62", kind: "SINK" },
  });
  expect(sink.status()).toBe(201);
  const definition = {
    ...original.snapshot.scenario.definition,
    name: "I3 captured bilingual " + randomUUID(),
    target_id: (await dut.json()).id,
    sink_id: (await sink.json()).id,
  };
  const library = await (await request.get("/api/v1/scenarios")).json();
  const saved = await request.post("/api/v1/scenarios", {
    data: { revision: library.revision, definition },
  });
  expect(saved.status()).toBe(201);
  const first = await saved.json();
  const updated = await request.put("/api/v1/scenarios/" + first.scenario.id, {
    data: {
      revision: first.revision,
      definition: {
        ...definition,
        objective:
          "Second captured OFFLINE definition; no live device activity.",
      },
    },
  });
  expect(updated.status()).toBe(200);
  const second = await updated.json();
  await page
    .getByRole("button", { name: "Reload scenarios", exact: true })
    .click();
  await expect(
    page.getByLabel("Saved scenario", { exact: true }),
  ).toContainText(definition.name);
  await page
    .getByLabel("Saved scenario", { exact: true })
    .selectOption(first.scenario.id);
  await expect(
    page.getByLabel("Scenario version", { exact: true }),
  ).toHaveValue("2");
  await page.getByLabel("Scenario version", { exact: true }).selectOption("1");
  await page
    .getByRole("button", { name: "Start OFFLINE preparation", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "View submitted run" }),
  ).toBeVisible();
  await expect
    .poll(() =>
      page.evaluate(() => sessionStorage.getItem("aiddos.s02.pending.v1")),
    )
    .toBeNull();
  await page.getByRole("button", { name: "View submitted run" }).click();
  await expect(page.locator(".runs-summary")).toContainText("QUEUED");
  await expect(page.locator("main")).toContainText(first.scenario.digest);
  const detailBefore = await page.evaluate(async () => {
    const path = "/src/pages/runs/controller.ts";
    const { runsController } = await import(/* @vite-ignore */ path);
    return runsController().view.detail;
  });
  expect(detailBefore.run.scenario_version).toBe(1);
  expect(detailBefore.snapshot.scenario).toEqual(first.scenario);
  await page
    .getByRole("button", { name: "Cancel OFFLINE run", exact: true })
    .click();
  await expect(page.locator(".runs-summary")).toContainText("CANCELLED");
  await page
    .getByRole("button", { name: "Reload events", exact: true })
    .click();
  await expect(page.locator(".runs-timeline")).toContainText("CANCELLED");
  await page
    .getByRole("button", { name: "Close details", exact: true })
    .click();
  await page.getByLabel("Scenario version", { exact: true }).selectOption("2");
  let committed: string | null = null;
  await page.route("**/api/v1/offline-runs", async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    const result = await route.fetch({ maxRedirects: 0 });
    expect(result.status()).toBe(202);
    const bytes = await result.body();
    writeFileSync(resolve(output, "actual-lost-ack.body"), bytes);
    committed = JSON.parse(bytes.toString()).run.id;
    await route.abort("failed");
  });
  await page
    .getByRole("button", { name: "Start OFFLINE preparation", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Submission recovery" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Retry saved request read" }),
  ).toBeEnabled();
  expect(committed).not.toBeNull();
  const savedReceipt = await page.evaluate(() =>
    sessionStorage.getItem("aiddos.s02.pending.v1"),
  );
  expect(JSON.parse(savedReceipt!).checkpoint).toBeNull();
  expect(posts.filter((p) => p === ep)).toHaveLength(2);
  await page.unroute("**/api/v1/offline-runs");
  const beforeReloadPosts = posts.length;
  await page.reload();
  await expect
    .poll(() =>
      page.evaluate(() => sessionStorage.getItem("aiddos.s02.pending.v1")),
    )
    .toBeNull();
  expect(posts.length).toBe(beforeReloadPosts);
  await page.getByRole("button", { name: "Refresh runs", exact: true }).click();
  const row = page.locator(".runs-table tr").filter({ hasText: committed! });
  await row.getByRole("button", { name: committed!, exact: true }).click();
  await expect(page.locator(".runs-summary")).toContainText("QUEUED");
  writeFileSync(
    resolve(output, "start-worker"),
    "explicit worker start after captured browser create and GET-only reload recovery\n",
  );
  await expect(page.locator(".runs-summary")).toContainText("SUCCEEDED");
  await expect(page.locator("main")).toContainText("NOT_EVALUATED");
  await expect(page.locator("main")).toContainText(
    "Defense not evaluated; measurements null; defense verdict null.",
  );
  const terminal = await request.get(ep + "/" + committed);
  expect(terminal.status()).toBe(200);
  const terminalBytes = await terminal.body();
  writeFileSync(resolve(output, "actual-browser-terminal.body"), terminalBytes);
  const value = JSON.parse(terminalBytes.toString());
  expect(value.run.scenario_version).toBe(2);
  expect(value.snapshot.scenario).toEqual(second.scenario);
  expect(value.result.evaluation).toBe("NOT_EVALUATED");
  expect(value.result.measurements).toBeNull();
  expect(value.result.defense_verdict).toBeNull();
  await page
    .getByRole("button", { name: "Reload events", exact: true })
    .click();
  await expect(page.locator(".runs-timeline")).toContainText("SUCCEEDED");
  expect(
    await page.evaluate(() => sessionStorage.getItem("aiddos.s02.pending.v1")),
  ).toBeNull();
  expect(posts.filter((p) => p === ep)).toHaveLength(2);
  await page.screenshot({
    path: info.outputPath("runs-en-desktop.png"),
    fullPage: true,
  });
  // Language control and native keyboard/focus checks use the actual shell, not a rendered fixture.
  const ko = page.getByRole("combobox", { name: /language/i });
  await ko.selectOption("ko");
  await expect(page.getByRole("heading", { name: "실행 이력" })).toBeVisible();
  await expect(page.locator("main")).toContainText("미평가");
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole("button", { name: "실행 시작" })).toBeDisabled();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: info.outputPath("runs-ko-mobile.png"),
    fullPage: true,
  });
  const retry = page.getByRole("button", {
    name: "실행 읽기 재시도",
    exact: true,
  });
  await retry.focus();
  await expect(retry).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(retry).toBeFocused();
  await Promise.all(pending);
  expect(external).toEqual([]);
  writeFileSync(
    resolve(output, "browser-http-index.json"),
    JSON.stringify(responses, null, 2),
  );
  writeFileSync(
    resolve(output, "browser-verification.json"),
    JSON.stringify(
      {
        realAPI: true,
        realPrivatePostgres: true,
        separateWorker: true,
        actualPostCount: posts.length,
        posts,
        reloadPostDelta: posts.length - beforeReloadPosts,
        external,
        scenarioId: first.scenario.id,
        terminalRunId: committed,
        terminalState: value.run.state,
        evaluation: value.result.evaluation,
      },
      null,
      2,
    ),
  );
});

test("owned ephemeral-origin denial preserves A; ordinary B is compiled by real separate worker without receipt adoption", async ({
  page,
  request,
}, info) => {
  const posts: string[] = [];
  page.on("request", (r) => {
    if (r.method() === "POST") posts.push(r.url());
  });
  const tag = randomUUID(),
    dut = await request.post("/api/v1/targets", {
      data: { name: tag + " DUT", address: "192.0.2.71", kind: "DUT" },
    }),
    sink = await request.post("/api/v1/targets", {
      data: { name: tag + " SINK", address: "192.0.2.72", kind: "SINK" },
    });
  expect(dut.status()).toBe(201);
  expect(sink.status()).toBe(201);
  const library = await (await request.get("/api/v1/scenarios")).json();
  const saved = await request.post("/api/v1/scenarios", {
    data: {
      revision: library.revision,
      definition: {
        ...original.snapshot.scenario.definition,
        name: tag,
        target_id: (await dut.json()).id,
        sink_id: (await sink.json()).id,
      },
    },
  });
  expect(saved.status()).toBe(201);
  const scenario = (await saved.json()).scenario;
  const bRequest = {
    request_id: randomUUID(),
    mode: "OFFLINE",
    scenario_id: scenario.id,
    scenario_version: scenario.version,
    scenario_digest: scenario.digest,
  };
  const response = await request.post(ep, { data: bRequest });
  expect(response.status()).toBe(202);
  const queuedBytes = await response.body(),
    queued = JSON.parse(queuedBytes.toString());
  writeFileSync(resolve(output, "native-created-B.body"), queuedBytes);
  writeFileSync(
    resolve(output, "native-created-B.metadata.json"),
    JSON.stringify(
      {
        method: "POST",
        path: ep,
        status: response.status(),
        request: bRequest,
        headers: response.headers(),
        body_sha256: createHash("sha256").update(queuedBytes).digest("hex"),
        provenance:
          "actual current-I3-source APIRequestContext prerequisite, not browser POST",
      },
      null,
      2,
    ),
  );
  await page.goto("/runs");
  await page
    .getByLabel("Saved scenario", { exact: true })
    .selectOption(scenario.id);
  await expect(
    page.getByRole("button", {
      name: "Start OFFLINE preparation",
      exact: true,
    }),
  ).toBeEnabled();
  await page
    .getByRole("button", { name: "Start OFFLINE preparation", exact: true })
    .click();
  await expect(page.getByRole("alert")).toContainText("Origin is not allowed");
  const pendingA = await page.evaluate(() =>
    sessionStorage.getItem("aiddos.s02.pending.v1"),
  );
  expect(pendingA).not.toBeNull();
  expect(JSON.parse(pendingA!).checkpoint).toBeNull();
  expect(posts).toHaveLength(1);
  await page.getByRole("button", { name: queued.run.id, exact: true }).click();
  await expect(page.locator(".runs-summary")).toContainText("QUEUED");
  expect(
    await page.evaluate(() => sessionStorage.getItem("aiddos.s02.pending.v1")),
  ).toBe(pendingA);
  writeFileSync(
    resolve(output, "start-worker"),
    "ordinary native-API-created B; NOT browser POST admission proof\n",
  );
  await expect(page.locator(".runs-summary")).toContainText("SUCCEEDED");
  await expect(
    page.getByText(
      "Defense not evaluated; measurements null; defense verdict null.",
    ),
  ).toBeVisible();
  expect(
    await page.evaluate(() => sessionStorage.getItem("aiddos.s02.pending.v1")),
  ).toBe(pendingA);
  expect(posts).toHaveLength(1);
  const terminal = await request.get(ep + "/" + queued.run.id);
  expect(terminal.status()).toBe(200);
  const terminalBytes = await terminal.body();
  writeFileSync(resolve(output, "ordinary-B-terminal.body"), terminalBytes);
  writeFileSync(
    resolve(output, "ordinary-B-terminal.metadata.json"),
    JSON.stringify(
      {
        method: "GET",
        path: ep + "/" + queued.run.id,
        status: terminal.status(),
        headers: terminal.headers(),
        body_sha256: createHash("sha256").update(terminalBytes).digest("hex"),
        provenance: "actual current-I3-source API + separate worker",
      },
      null,
      2,
    ),
  );
  const value = JSON.parse(terminalBytes.toString());
  expect(value.run.id).toBe(queued.run.id);
  expect(value.snapshot).toEqual(queued.snapshot);
  expect(value.result.measurements).toBeNull();
  expect(value.result.defense_verdict).toBeNull();
  await page
    .getByRole("button", { name: "Reload events", exact: true })
    .click();
  await expect(page.locator(".runs-timeline")).toContainText("SUCCEEDED");
  const close = page.getByRole("button", {
    name: "Close details",
    exact: true,
  });
  await close.focus();
  await page.keyboard.press("Enter");
  await expect(
    page.getByRole("button", { name: queued.run.id, exact: true }),
  ).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.locator(".runs-summary")).toContainText("SUCCEEDED");
  for (const width of [1440, 1024, 390]) {
    await page.setViewportSize({ width, height: 1000 });
    await page.evaluate(() => window.scrollTo(0, 0));
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
    await page.screenshot({
      path: info.outputPath(`ordinary-en-${width}.png`),
      fullPage: true,
    });
  }
  await page
    .getByRole("combobox", { name: "Interface language" })
    .selectOption("ko");
  await expect(page.getByRole("heading", { name: "실행 이력" })).toBeVisible();
  await expect(page.locator(".runs-summary")).toContainText("방어 결과 미평가");
  await expect(
    page.getByRole("button", { name: "실행 시작", exact: true }),
  ).toBeDisabled();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({
    path: info.outputPath("ordinary-ko-390.png"),
    fullPage: true,
  });
  const accessibility = await new AxeBuilder({ page })
    .include(".runs-page")
    .analyze();
  writeFileSync(
    resolve(output, "runs-axe.json"),
    JSON.stringify(accessibility, null, 2),
  );
  expect(accessibility.violations).toEqual([]);
  const before = posts.length;
  await page.reload();
  await expect(
    page.getByRole("button", { name: queued.run.id, exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: queued.run.id, exact: true }).click();
  await expect(page.locator(".runs-summary")).toContainText("SUCCEEDED");
  expect(posts).toHaveLength(before);
  expect(
    await page.evaluate(() => sessionStorage.getItem("aiddos.s02.pending.v1")),
  ).toBe(pendingA);
  writeFileSync(
    resolve(output, "ordinary-browser-verification.json"),
    JSON.stringify(
      {
        scope:
          "actual ordinary B browser read/poll + real separate worker; NOT browser POST admission acceptance",
        queuedRun: queued.run.id,
        terminalState: value.run.state,
        pendingAPreserved: true,
        browserPOSTStatus: 403,
        browserPosts: posts.length,
        reloadGETOnly: true,
        measurements: value.result.measurements,
        verdict: value.result.defense_verdict,
      },
      null,
      2,
    ),
  );
});

test("exact-byte Node/Chromium parity uses the same shipped parser and provenance-labelled corpus", async ({
  page,
}, info) => {
  await page.goto("/runs");
  const directory = resolve(root, "tests/fixtures/runs/parity");
  const manifest = JSON.parse(
    readFileSync(resolve(directory, "manifest.json"), "utf8"),
  );
  const results = [];
  for (let i = 0; i < manifest.length; i += 100) {
    const batch = manifest
      .slice(i, i + 100)
      .map(
        (e: {
          file: string;
          sha256: string;
          context: unknown;
          expected: string;
        }) => {
          const raw = readFileSync(resolve(directory, e.file));
          expect(createHash("sha256").update(raw).digest("hex")).toBe(e.sha256);
          return { ...e, base64: raw.toString("base64") };
        },
      );
    const outcomes = await page.evaluate(async (entries) => {
      const path = "/src/pages/runs/client.ts";
      const { decodeResponse } = await import(/* @vite-ignore */ path);
      const outcomes = [];
      for (const entry of entries) {
        const bytes = Uint8Array.from(atob(entry.base64), (c) =>
          c.charCodeAt(0),
        );
        const hash = Array.from(
          new Uint8Array(await crypto.subtle.digest("SHA-256", bytes)),
          (n) => n.toString(16).padStart(2, "0"),
        ).join("");
        let verdict = "ACCEPT";
        try {
          await decodeResponse(bytes, entry.context);
        } catch (e) {
          verdict = (e as { code?: string }).code ?? "REJECT";
        }
        outcomes.push({ file: entry.file, hash, verdict });
      }
      return outcomes;
    }, batch);
    expect(outcomes).toEqual(
      batch.map((e: { file: string; sha256: string; expected: string }) => ({
        file: e.file,
        hash: e.sha256,
        verdict: e.expected,
      })),
    );
    results.push(...outcomes);
  }
  expect(results).toHaveLength(manifest.length);
  writeFileSync(
    resolve(output, "chromium-parity.json"),
    JSON.stringify(results, null, 2),
  );
  await info.attach("exact-byte-parity-count", {
    body: JSON.stringify({
      count: results.length,
      provenance:
        "earlier-source H1 HTTP + explicitly synthetic mutations; not final W2 parity",
    }),
    contentType: "application/json",
  });
});
