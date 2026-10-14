import { test, expect } from "@playwright/test";
import { appendFileSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { createHash } from "node:crypto";

const output = process.env.P1_OUTPUT!;
const workspace = process.env.P1_WORKSPACE!;
const state = JSON.parse(readFileSync(join(workspace, "workspace.json"), "utf8"));
const ep = "/api/v1/offline-runs";

test("one real browser scenario and explicit supervised OFFLINE worker", async ({ page, context }) => {
  const network: Promise<void>[] = [];
  const denied: string[] = [];
  const errors: string[] = [];
  const mutations: string[] = [];
  let serial = 0;
  const record = (value: unknown) => appendFileSync(join(output, "network.jsonl"), JSON.stringify(value) + "\n");
  const save = (name: string, value: unknown) => writeFileSync(join(output, name), JSON.stringify(value, null, 2) + "\n");
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("request", (r) => {
    record({ kind: "request", url: r.url(), method: r.method(), body: r.postData() });
    if (r.method() === "POST") mutations.push(new URL(r.url()).pathname);
  });
  page.on("response", (r) => {
    if (new URL(r.url()).pathname.startsWith("/api/")) {
      const file = `response-${serial++}.body`;
      network.push((async () => {
        const bytes = await r.body();
        writeFileSync(join(output, file), bytes);
        record({ kind: "response", url: r.url(), status: r.status(), file,
          sha256: createHash("sha256").update(bytes).digest("hex") });
      })());
    }
  });
  await context.route("**/*", async route => {
    if (new URL(route.request().url()).origin !== state.origin) {
      denied.push(route.request().url());
      await route.abort("blockedbyclient");
    } else await route.continue();
  });
  await context.routeWebSocket("**/*", route => {
    if (new URL(route.url()).origin !== state.origin.replace("http:", "ws:")) {
      denied.push(route.url()); route.close();
    } else route.connectToServer();
  });

  let runId = process.env.P1_RETAINED_RUN;
  let scenario: Record<string, unknown> | undefined;
  if (!runId) {
    await page.goto("/runs");
    await expect(page.getByText("No OFFLINE runs yet")).toBeVisible();
    // These are literal inert draft addresses, not devices or transmission targets.
    await page.goto("/targets");
    const targets: string[] = [];
    for (const [kind, address] of [["DUT", "192.0.2.71"], ["SINK", "192.0.2.72"]]) {
      await page.getByRole("button", { name: "Add target", exact: true }).click();
      const dialog = page.getByRole("dialog");
      await dialog.getByLabel("Name", { exact: true }).fill(`Phase1 ${kind} inert metadata`);
      await dialog.getByLabel("IP address or hostname", { exact: true }).fill(address);
      await dialog.getByLabel("Role", { exact: true }).selectOption(kind);
      const reply = page.waitForResponse(r => r.request().method() === "POST" && new URL(r.url()).pathname === "/api/v1/targets");
      await dialog.getByRole("button", { name: "Save draft", exact: true }).click();
      const response = await reply;
      expect(response.status()).toBe(201);
      targets.push((await response.json()).id);
      await expect(dialog).not.toBeVisible();
    }
    await page.goto("/profiles");
    await page.getByRole("button", { name: "New scenario", exact: true }).click();
    const dialog = page.getByRole("dialog");
    for (const [label, value] of [
      ["Scenario name", "Phase1 supervised preparation / 감독 OFFLINE"],
      ["Objective", "Prepare one manifest only; no packets, device access, telemetry or verdict."],
      ["DUT version", "metadata-only"], ["Policy version", "offline-v1"],
      ["Maximum PPS", "100"], ["Maximum BPS", "1000"], ["Maximum packets", "1000"],
      ["Maximum bytes", "10000"], ["Maximum connections", "10"], ["Duration (seconds)", "10"],
      ["Minimum delivery (%)", "95"], ["Maximum delivery (%)", "100"],
      ["Maximum legitimate loss (%)", "1"], ["Maximum service latency (ms)", "100"],
    ]) await dialog.getByLabel(label, { exact: true }).fill(value);
    await dialog.getByLabel("DUT target", { exact: true }).selectOption(targets[0]);
    await dialog.getByLabel("Sink target", { exact: true }).selectOption(targets[1]);
    for (const label of ["Ingress PCAP", "Egress PCAP", "Service probe"]) {
      await dialog.getByLabel(label, { exact: true }).check();
    }
    const saved = page.waitForResponse(r => r.request().method() === "POST" && new URL(r.url()).pathname === "/api/v1/scenarios");
    await dialog.getByRole("button", { name: "Save scenario", exact: true }).click();
    const response = await saved;
    expect(response.status()).toBe(201);
    scenario = (await response.json()).scenario;
    save("scenario.json", scenario);
    await expect(dialog).not.toBeVisible();
    await page.goto("/runs");
    await page.getByLabel("Saved scenario", { exact: true }).selectOption(String(scenario!.id));
    await expect(page.getByLabel("Scenario version", { exact: true })).toHaveValue("1");
    const queued = page.waitForResponse(r => r.request().method() === "POST" && new URL(r.url()).pathname === ep);
    await page.getByRole("button", { name: "Start OFFLINE preparation", exact: true }).click();
    const accepted = await queued;
    expect(accepted.status()).toBe(202);
    const value = await accepted.json();
    runId = value.run.id;
    expect(value.run.state).toBe("QUEUED");
    save("queued.json", { run_id: runId, accepted: value, workspace });
    await page.getByRole("button", { name: "View submitted run", exact: true }).click();
    await expect(page.locator(".runs-summary")).toContainText("QUEUED");
    await page.screenshot({ path: join(output, "queued.png"), fullPage: true });
    console.log(`Explicit operator command required now: tools/phase1_local.py worker --workspace ${workspace} --run-id ${runId}`);
    // The test never launches a worker, sends an execution HTTP call, or retries a run.
    await expect(page.locator(".runs-summary")).toContainText("SUCCEEDED", { timeout: 80_000 });
  } else {
    await page.goto("/runs");
    await page.getByRole("button", { name: runId, exact: true }).click();
    await expect(page.locator(".runs-summary")).toContainText("SUCCEEDED");
  }
  await expect(page.locator("main")).toContainText("NOT_EVALUATED");
  await expect(page.locator("main")).toContainText("Defense not evaluated; measurements null; defense verdict null.");
  await page.getByRole("button", { name: "Reload events", exact: true }).click();
  await expect(page.locator(".runs-timeline")).toContainText("SUCCEEDED");
  const actual = await page.evaluate(async url => {
    const response = await fetch(url); return { status: response.status, body: await response.text() };
  }, ep + "/" + runId);
  expect(actual.status).toBe(200);
  writeFileSync(join(output, "terminal.body"), actual.body);
  const terminal = JSON.parse(actual.body);
  expect(terminal.run.state).toBe("SUCCEEDED");
  expect(terminal.run.attempt).toBe(1);
  expect(terminal.result.evaluation).toBe("NOT_EVALUATED");
  expect(terminal.result.measurements).toBeNull();
  expect(terminal.result.defense_verdict).toBeNull();
  if (scenario) expect(terminal.snapshot.scenario).toEqual(scenario);
  await page.screenshot({ path: join(output, "terminal-en.png"), fullPage: true });
  await page.getByRole("combobox", { name: /Interface language|화면 언어/ }).selectOption("ko");
  await expect(page.getByRole("heading", { name: "실행 이력", exact: true })).toBeVisible();
  await expect(page.locator(".runs-summary")).toContainText("SUCCEEDED");
  await expect(page.locator("main")).toContainText("방어 미평가; 측정값 null; 방어 판정 null.");
  await page.screenshot({ path: join(output, "terminal-ko.png"), fullPage: true });
  await Promise.all(network);
  expect(errors).toEqual([]);
  expect(denied).toEqual([]);
  expect(mutations.filter(p => p === ep)).toHaveLength(process.env.P1_RETAINED_RUN ? 0 : 1);
  expect(mutations.filter(p => p === "/api/v1/scenarios")).toHaveLength(process.env.P1_RETAINED_RUN ? 0 : 1);
  save("browser-result.json", { run_id: runId, scenario_id: terminal.run.scenario_id,
    state: terminal.run.state, attempt: terminal.run.attempt, errors, denied, mutations,
    read_only_reopen: Boolean(process.env.P1_RETAINED_RUN), evaluation: "NOT_EVALUATED" });
});
