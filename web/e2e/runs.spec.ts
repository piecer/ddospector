import { test as baseTest, expect } from "@playwright/test";
import type { Page } from "@playwright/test";
import { literalGeometry } from "./runs-geometry";
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
async function keyboardRoute(page: Page, route: string) {
  await page.keyboard.press("Control+k");
  const search = page.getByRole("textbox", { name: /Find a page|메뉴 찾기/ });
  await expect(search).toBeFocused();
  await search.fill(route);
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(new RegExp('/' + route + '$'));
}
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
  const mutations: { method: string; path: string }[] = [];
  const a19 = ["en", "ko"].flatMap((locale) => [1440, 1024, 390].map((width) => ({
    locale, width, status: "NOT_REACHED", observations: {} as Record<string, unknown>,
  })));
  const locks: Record<string, unknown>[] = [];
  const publishA19 = () => writeFileSync(resolve(output, "a19-matrix.json"), JSON.stringify({
    scope: "new bounded A19 normal-flow coverage; not product repair or full A19/A18/S02 acceptance",
    rows: a19, locks, mutations,
  }, null, 2));
  publishA19();
  page.on("request", (r) => {
    if (!["GET", "HEAD", "OPTIONS"].includes(r.method())) {
      mutations.push({ method: r.method(), path: new URL(r.url()).pathname });
    }
  });
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
  // A local draft prerequisite exposes the retained Campaign LIVE lock; no run is created.
  const campaignResponse = await request.post("/api/v1/campaigns", { data: {
    name: "A19 retained LIVE lock", objective: "UI lock observation only; no execution.",
    target_id: definition.target_id, profile_id: definition.profile_id,
  } });
  expect(campaignResponse.status()).toBe(201);
  const campaign = await campaignResponse.json();
  writeFileSync(resolve(output, "a19-campaign-draft.body"), await campaignResponse.body());
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
  const matrixBaseline = mutations.slice();
  for (const witness of a19) {
    witness.status = "RUNNING";
    publishA19();
    const { locale, width } = witness;
    const ko = locale === "ko";
    const label = (en: string, korean: string) => ko ? korean : en;
    try {
      await page.setViewportSize({ width, height: 1000 });
      const language = page.getByRole("combobox", { name: /Interface language|화면 언어/ });
      await language.focus();
      await expect(language).toBeFocused();
      // Native select keyboard changes, not dispatchEvent or a mocked locale.
      await page.keyboard.press(ko ? "End" : "Home");
      await expect(language).toHaveValue(locale);
      await expect(language).toBeFocused();
      await expect(page.locator("html")).toHaveAttribute("lang", locale);
      await expect(page.getByRole("heading", { name: label("Run history", "실행 이력"), exact: true })).toBeVisible();
      await expect(page.getByRole("button", { name: label("Start run", "실행 시작"), exact: true })).toBeDisabled();
      await expect(page.getByRole("button", { name: label("Cancel OFFLINE run", "OFFLINE 실행 취소"), exact: true })).toBeDisabled();
      const boundary = page.locator(".runs-boundary");
      await expect(boundary).toContainText("NOT_EVALUATED");
      await expect(boundary).toContainText(label(
        "Measurements and defense verdict remain null. No captured packets or device evidence have been ingested.",
        "측정값과 방어 판정은 null입니다. 캡처 패킷이나 장비 증거를 가져오지 않았습니다.",
      ));
      const nullEvidence = page.getByText(label(
        "Defense not evaluated; measurements null; defense verdict null.",
        "방어 미평가; 측정값 null; 방어 판정 null.",
      ), { exact: true });
      await expect(nullEvidence).toBeVisible();
      await expect(page.locator(".runs-summary")).toContainText("SUCCEEDED");
      const retryRead = page.getByRole("button", { name: label("Retry run read", "실행 읽기 재시도"), exact: true });
      await retryRead.focus();
      const read = page.waitForResponse((r) => new URL(r.url()).pathname === ep + "/" + committed && r.request().method() === "GET");
      await page.keyboard.press("Enter");
      const readResponse = await read;
      expect(readResponse.status()).toBe(200);
      expect(await readResponse.json()).toEqual(value);
      await expect(retryRead).toBeEnabled();
      await expect(retryRead).toBeFocused();
      witness.observations.readRetry = { status: readResponse.status(), method: "GET", exactTerminal: true, focusRetained: true };
      const region = page.getByRole("region", { name: label("Retained OFFLINE runs", "보관된 OFFLINE 실행"), exact: true });
      await region.focus();
      await expect(region).toBeFocused();
      const beforeScroll = await region.evaluate((e) => ({ left: e.scrollLeft, width: e.clientWidth, extent: e.scrollWidth }));
      if (beforeScroll.extent > beforeScroll.width) {
        await page.keyboard.press("ArrowRight");
        await expect.poll(() => region.evaluate((e) => e.scrollLeft)).toBeGreaterThan(beforeScroll.left);
      }
      witness.observations.tableScroll = { before: beforeScroll, after: await region.evaluate((e) => e.scrollLeft) };
      const runButton = page.getByRole("button", { name: committed!, exact: true });
      await runButton.focus();
      await expect(runButton).toBeFocused();
      await page.keyboard.press("Enter");
      const closeDetails = page.getByRole("button", { name: label("Close details", "상세 닫기"), exact: true });
      await closeDetails.focus();
      await page.keyboard.press("Enter");
      await expect(runButton).toBeFocused();
      await page.keyboard.press("Enter");
      await expect(page.locator(".runs-summary")).toContainText("SUCCEEDED");
      witness.observations.closeReopen = { keyboard: "Enter", invokerFocusRestored: true };
      const details = page.locator(".panel").filter({ has: page.getByRole("heading", { name: label("Run details", "실행 상세"), exact: true }) });
      const scenarioSummary = details.locator("summary").filter({ hasText: label("Captured scenario and declared limits", "캡처 시나리오와 선언된 제한") });
      await scenarioSummary.focus();
      await page.keyboard.press("Enter");
      await expect(details.locator(".scenario-record")).toBeVisible();
      const literals = [
        ["run_id", details.locator("p.runs-identity").filter({ hasText: committed! }), committed!],
        ["history_run_id", runButton, committed!],
        ["scenario_digest", details.locator(".scenario-record dd").filter({ hasText: value.snapshot.scenario.digest }), value.snapshot.scenario.digest],
        ["snapshot_digest", details.locator("dd").filter({ hasText: value.snapshot.digest }), value.snapshot.digest],
        ["result_digest", details.locator("p.runs-identity").filter({ hasText: value.result.digest }), value.result.digest],
      ] as const;
      const measured: Record<string, unknown> = {};
      witness.observations.literals = measured;
      for (const [name, locator, literal] of literals) {
        const geometry = await literalGeometry(locator, literal);
        measured[name] = geometry;
        publishA19();
        expect(geometry.rectangles.length).toBeGreaterThan(0);
        expect(geometry.inaccessible, name).toEqual([]);
        expect(geometry.documentWidth).toBeLessThanOrEqual(geometry.viewportWidth);
      }
      const jsonSummary = details.locator("summary").filter({ hasText: label("Complete verified record (JSON)", "검증된 전체 기록 (JSON)") });
      await jsonSummary.focus();
      await page.keyboard.press("Enter");
      await page.keyboard.press("Tab");
      const jsonRecord = details.locator("pre");
      await expect(jsonRecord).toBeFocused();
      expect(JSON.parse((await jsonRecord.textContent())!)).toEqual(value);
      await page.keyboard.press("Control+End");
      await expect.poll(() => jsonRecord.evaluate((e) => e.scrollHeight - e.clientHeight - e.scrollTop)).toBeLessThanOrEqual(1);
      witness.observations.fullRecord = { exactHTTPRecord: true, keyboardFocus: true,
        scroll: await jsonRecord.evaluate((e) => ({ top: e.scrollTop, height: e.clientHeight, extent: e.scrollHeight })) };
      await page.keyboard.press("Shift+Tab");
      await expect(jsonSummary).toBeFocused();
      await page.keyboard.press("Enter");
      const screenshot = `a19-${locale}-${width}.png`;
      await page.screenshot({ path: info.outputPath(screenshot), fullPage: true });
      witness.observations.screenshot = info.outputPath(screenshot);
      await scenarioSummary.focus();
      await page.keyboard.press("Enter");
      expect(mutations).toEqual(matrixBaseline);
      witness.observations.mutationDelta = mutations.length - matrixBaseline.length;
      witness.observations.notEvaluatedAndNullVisible = true;
      witness.observations.liveAndTerminalCancelDisabled = true;
      witness.status = "PASS";
    } catch (error) {
      witness.status = "FAIL";
      witness.observations.error = String(error);
      throw error;
    } finally { publishA19(); }
  }
  expect(a19).toHaveLength(6);
  expect(a19.every((row) => row.status === "PASS")).toBe(true);
  await page.getByRole("combobox", { name: /Interface language|화면 언어/ }).selectOption("en");
  await page.setViewportSize({ width: 1440, height: 1000 });
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
  for (const locale of ["en", "ko"]) {
    const lock: Record<string, unknown> = { locale, status: "RUNNING" };
    locks.push(lock);
    publishA19();
    try {
      const label = (en: string, korean: string) => locale === "ko" ? korean : en;
      await page.getByRole("combobox", { name: /Interface language|화면 언어/ }).selectOption(locale);
      await keyboardRoute(page, "agent");
      await expect(page.getByRole("button", { name: label("Run agent", "에이전트 실행"), exact: true })).toBeDisabled();
      await expect(page.getByRole("button", { name: label("Connect MCP", "MCP 연결"), exact: true })).toBeDisabled();
      lock.agent = { runDisabled: true, connectMCPDisabled: true };
      await page.screenshot({ path: info.outputPath(`a19-agent-${locale}-390.png`), fullPage: true });
      await keyboardRoute(page, "campaigns");
      const campaignButton = page.getByRole("button", { name: campaign.name, exact: true });
      await campaignButton.focus();
      await page.keyboard.press("Enter");
      const dialog = page.getByRole("dialog", { name: label("Campaign draft details", "캠페인 초안 상세"), exact: true });
      await expect(dialog).toBeVisible();
      await expect(dialog.getByRole("button", { name: label("Start run", "실행 시작"), exact: true })).toBeDisabled();
      await expect(dialog.locator("#campaign-run-reason")).toHaveText(label(
        "This draft grants no execution authority. The server does not allow live runs.",
        "이 초안은 실행을 승인하지 않습니다. 서버에서 라이브 실행을 허용하지 않습니다.",
      ));
      await page.screenshot({ path: info.outputPath(`a19-campaign-${locale}-390.png`), fullPage: true });
      await page.keyboard.press("Escape");
      await expect(dialog).not.toBeVisible();
      await expect(campaignButton).toBeFocused();
      lock.campaign = { id: campaign.id, startDisabled: true, escapeRestoresFocus: true };
      expect(mutations).toEqual(matrixBaseline);
      lock.mutationDelta = mutations.length - matrixBaseline.length;
      lock.status = "PASS";
    } catch (error) { lock.status = "FAIL"; lock.error = String(error); throw error; }
    finally { publishA19(); }
  }
  expect(posts.filter((path) => path.endsWith("/cancel"))).toHaveLength(1);
  expect(mutations).toEqual(matrixBaseline);
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
