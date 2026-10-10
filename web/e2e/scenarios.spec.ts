import { createHash, randomUUID } from "node:crypto";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test, type APIRequestContext } from "@playwright/test";

const endpoint = "/api/v1/scenarios";
const projectRoot = resolve(dirname(fileURLToPath(import.meta.url)), "../..");

test("fresh Python API bytes and raw-token mutations pass through the shipped Chromium client", async ({
  page,
}, info) => {
  const output = info.outputPath("producer");
  execFileSync(
    join(projectRoot, ".venv/bin/python"),
    ["tests/api/scenario_producer.py", "--out", output],
    { cwd: projectRoot, timeout: 30_000 },
  );
  const receipt = JSON.parse(
    readFileSync(join(output, "receipt.json"), "utf8"),
  );
  const samples = receipt.samples.map(
    (sample: {
      file: string;
      kind: string;
      status: number;
      method: string;
      request: unknown;
    }) => ({
      ...sample,
      raw: readFileSync(join(output, sample.file), "utf8"),
    }),
  );
  expect(samples.length).toBe(receipt.sample_count);
  await page.goto("/");
  const results = await page.evaluate(async (items) => {
    const path = "/src/pages/scenarios/client.ts";
    const { scenarioAPI } = await import(/* @vite-ignore */ path);
    const original = window.fetch;
    const outcomes = [];
    try {
      for (const item of items) {
        const value = JSON.parse(item.raw);
        let requests = 0;
        window.fetch = async () => {
          requests++;
          return new Response(new TextEncoder().encode(item.raw), {
            status: item.status,
            headers: { "Content-Type": "application/json" },
          });
        };
        try {
          let result;
          if (item.kind === "mutation")
            result = await scenarioAPI.save({
              ...item.request,
              opened:
                item.method === "POST"
                  ? null
                  : {
                      id: value.scenario.id,
                      version: value.scenario.version - 1,
                    },
            });
          else if (item.kind === "history")
            result = await scenarioAPI.history(value.scenario_id);
          else
            result = await scenarioAPI.read(
              value.offset ?? 0,
              value.limit ?? 50,
            );
          outcomes.push({ file: item.file, accepted: true, requests, result });
        } catch (error) {
          outcomes.push({
            file: item.file,
            accepted: false,
            requests,
            code: (error as { code?: string }).code,
          });
        }
      }
    } finally {
      window.fetch = original;
    }
    return outcomes;
  }, samples);
  for (let i = 0; i < samples.length; i++) {
    const sample = samples[i],
      result = results[i];
    expect(result.requests, sample.file).toBe(1);
    expect(result.accepted, sample.file).toBe(sample.kind !== "error");
    if (sample.kind === "error")
      expect(result.code, sample.file).toBe(JSON.parse(sample.raw).code);
    else expect(result.result, sample.file).toEqual(JSON.parse(sample.raw));
  }
  const raw = samples.find(
    (sample: { file: string }) => sample.file === "replay-create.json",
  ).raw;
  const invalid = [
    raw.replace('"revision":1', '"revision":1,"revision":1'),
    raw.replace('"revision":1', '"revision":1,"revis\\u0069on":1'),
    raw.replace('"revision":1', '"revision":1.0'),
    raw.replace('"revision":1', '"revision":1e0'),
    raw.replace('"revision":1', '"revision":true'),
    raw.replace('"revision":1', '"revision":"1"'),
    raw.replace('"ip_version":4', '"ip_version":4.0'),
    raw.replace('"max_pps":10', '"max_pps":1e1'),
    raw.replace('"execution_enabled":false', '"execution_enabled":0'),
    raw.slice(0, -1) + ',"unknown":1}',
    "[".repeat(34) + "0" + "]".repeat(34),
  ];
  expect(invalid.every((text) => text !== raw)).toBe(true);
  const rejected = await page.evaluate(
    async ({ raw, invalid }) => {
      const path = "/src/pages/scenarios/client.ts";
      const { scenarioAPI } = await import(/* @vite-ignore */ path);
      const original = window.fetch;
      const input = JSON.parse(raw),
        outcomes = [];
      const encoded = invalid.map((text) => new TextEncoder().encode(text));
      encoded.push(new Uint8Array([0xff, 0xfe]));
      try {
        for (const bytes of encoded) {
          window.fetch = async () => new Response(bytes, { status: 201 });
          try {
            await scenarioAPI.save({
              revision: 0,
              definition: input.scenario.definition,
              opened: null,
            });
            outcomes.push(false);
          } catch {
            outcomes.push(true);
          }
        }
      } finally {
        window.fetch = original;
      }
      return outcomes;
    },
    { raw, invalid },
  );
  expect(rejected).toEqual(Array(invalid.length + 1).fill(true));
  await info.attach("producer-consumer-results.json", {
    body: JSON.stringify({ results, malformed: rejected }),
    contentType: "application/json",
  });
});

function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value !== null && typeof value === "object") {
    const record = value as Record<string, unknown>;
    return `{${Object.keys(record)
      .sort()
      .map((key) => `${JSON.stringify(key)}:${canonical(record[key])}`)
      .join(",")}}`;
  }
  return JSON.stringify(value);
}

async function registeredTargets(request: APIRequestContext) {
  const tag = randomUUID();
  const dutResponse = await request.post("/api/v1/targets", {
    data: { name: `Scenario DUT ${tag}`, address: "192.0.2.10", kind: "DUT" },
  });
  expect(dutResponse.status()).toBe(201);
  const sinkResponse = await request.post("/api/v1/targets", {
    data: { name: `Scenario sink ${tag}`, address: "192.0.2.20", kind: "SINK" },
  });
  expect(sinkResponse.status()).toBe(201);
  return { dut: await dutResponse.json(), sink: await sinkResponse.json() };
}

function definition(targetId: string, sinkId: string) {
  return {
    name: `Scenario ${randomUUID()}`,
    objective:
      "Compare the declared policy with independently retained evidence.",
    target_id: targetId,
    sink_id: sinkId,
    dut_version: "fixture-firmware-1",
    policy_version: "fixture-policy-1",
    profile_id: "tcpreplay-policy",
    protocol: "TCP",
    ip_version: 4,
    expected_action: "BLOCK",
    delivery_expectation: "BLOCK",
    detection_required: true,
    pcap_asset: null,
    traffic_budget: {
      max_pps: 10,
      max_bps: 10000,
      max_packets: 100,
      max_bytes: 100000,
      max_connections: 1,
      duration_seconds: 10,
    },
    success_criteria: {
      minimum_delivery_pct: 0,
      maximum_delivery_pct: 0,
      detection_deadline_ms: 1000,
    },
    stop_conditions: {
      max_legitimate_loss_pct: 1,
      max_service_latency_ms: 1000,
      max_cpu_pct: null,
      max_memory_pct: null,
      max_sessions: null,
      management_loss: true,
    },
    evidence_requirements: [
      "ingress_pcap",
      "egress_pcap",
      "dut_events",
      "service_probe",
    ],
  };
}

function verifyDigest(record: Record<string, unknown>) {
  const { digest, ...unsigned } = record;
  expect(digest).toBe(
    createHash("sha256").update(canonical(unsigned), "utf8").digest("hex"),
  );
}

for (const mode of [
  "wrong-definition",
  "wrong-digest",
  "readback-failure",
  "concurrent-append",
  "real-CAS-conflict",
  "commit-uncertain",
  "pending-close",
] as const) {
  test(`real scenario browser mutation lifecycle: ${mode}`, async ({
    page,
    request,
  }, info) => {
    const { dut, sink } = await registeredTargets(request);
    const value = definition(dut.id, sink.id);
    const initial = await (await request.get(endpoint)).json();
    const response = await request.post(endpoint, {
      data: { revision: initial.revision, definition: value },
    });
    expect(response.status()).toBe(201);
    const created = await response.json();
    const path = `${endpoint}/${created.scenario.id}`;
    await page.goto("/profiles");
    const card = page
      .locator(".scenario-list article")
      .filter({
        has: page.getByRole("heading", { name: value.name, exact: true }),
      });
    await card
      .getByRole("button", { name: "Scenario history", exact: true })
      .click();
    await page
      .getByRole("dialog")
      .getByRole("button", { name: "Edit scenario", exact: true })
      .click();
    const editor = page.getByRole("dialog", {
      name: "Edit scenario",
      exact: true,
    });
    await editor
      .getByLabel("Policy version", { exact: true })
      .fill("preserved-submission");
    let puts = 0,
      failHistory = mode === "readback-failure";
    let release!: () => void, entered!: () => void;
    const held = new Promise<void>((done) => {
      release = done;
    });
    const enteredPut = new Promise<void>((done) => {
      entered = done;
    });
    let captured: unknown;
    await page.route(`**${path}`, async (route) => {
      if (route.request().method() === "GET") {
        if (failHistory)
          return route.fulfill({
            status: 503,
            contentType: "application/json",
            body: JSON.stringify({
              code: "SCENARIO_STATE_UNAVAILABLE",
              message: "Injected readback failure.",
            }),
          });
        return route.continue();
      }
      if (route.request().method() !== "PUT") return route.continue();
      puts++;
      const actual = await route.fetch();
      const body = await actual.json();
      captured = body;
      if (mode === "wrong-definition") {
        body.scenario.definition.objective =
          "Different valid definition returned instead of captured submission.";
        const { digest: _digest, ...unsigned } = body.scenario;
        body.scenario.digest = createHash("sha256")
          .update(canonical(unsigned), "utf8")
          .digest("hex");
      } else if (mode === "wrong-digest") body.scenario.digest = "0".repeat(64);
      else if (mode === "concurrent-append") {
        const later = await request.put(path, {
          data: {
            revision: body.revision,
            definition: {
              ...body.scenario.definition,
              policy_version: "concurrent-later",
            },
          },
        });
        expect(later.status()).toBe(200);
      } else if (mode === "commit-uncertain") {
        return route.fulfill({
          status: 503,
          contentType: "application/json",
          body: JSON.stringify({
            code: "SCENARIO_COMMIT_UNCERTAIN",
            message: "Injected uncertainty after actual publication.",
          }),
        });
      } else if (mode === "pending-close") {
        entered();
        await held;
      }
      await route.fulfill({ response: actual, body: canonical(body) });
    });
    if (mode === "real-CAS-conflict") {
      const competitor = await request.put(path, {
        data: {
          revision: created.revision,
          definition: { ...value, policy_version: "competing-writer" },
        },
      });
      expect(competitor.status()).toBe(200);
    }
    try {
      await editor
        .getByRole("button", { name: "Save new version", exact: true })
        .click();
      if (mode === "pending-close") {
        await enteredPut;
        await expect(
          editor.getByRole("button", { name: "Save new version", exact: true }),
        ).toBeDisabled();
        await editor
          .getByRole("button", { name: "Close", exact: true })
          .click();
        await expect(editor).not.toBeVisible();
        const nextFocus = page.locator("button:enabled").first();
        await nextFocus.focus();
        release();
        await expect(
          page.getByText(
            "Scenario saved and verified in immutable history. No execution was started.",
            { exact: true },
          ),
        ).toBeVisible();
        await expect(editor).not.toBeVisible();
        await expect(nextFocus).toBeFocused();
      } else if (mode === "concurrent-append") {
        await expect(editor).not.toBeVisible();
        await expect(
          page.getByText(
            "Scenario saved and verified in immutable history. No execution was started.",
            { exact: true },
          ),
        ).toBeVisible();
      } else {
        const retry = editor.getByRole("button", {
          name: "Retry acknowledgement read",
          exact: true,
        });
        await expect(retry).toBeVisible();
        await expect(
          editor.getByLabel("Policy version", { exact: true }),
        ).toHaveValue("preserved-submission");
        await expect(
          editor.getByRole("button", { name: "Save new version", exact: true }),
        ).toBeDisabled();
        failHistory = false;
        await retry.click();
        if (mode === "readback-failure") await expect(editor).not.toBeVisible();
        else {
          await expect(retry).toBeEnabled();
          await expect(
            editor.getByRole("button", {
              name: "Save new version",
              exact: true,
            }),
          ).toBeDisabled();
          await expect(
            page.getByText(
              "Scenario saved and verified in immutable history. No execution was started.",
              { exact: true },
            ),
          ).toHaveCount(0);
          await editor
            .getByRole("button", { name: "Close", exact: true })
            .click();
          await expect(editor).not.toBeVisible();
        }
      }
      expect(puts).toBe(1);
      const history = await (await request.get(path)).json();
      expect(history.versions[0]).toEqual(created.scenario);
      expect(history.versions).toHaveLength(
        mode === "concurrent-append" ? 3 : 2,
      );
      await info.attach("mutation-lifecycle.json", {
        body: JSON.stringify({ mode, puts, captured, history }),
        contentType: "application/json",
      });
    } finally {
      release();
    }
  });
}

test("scenario initial read failure stays distinct from an empty library and recovers only by GET", async ({
  page,
  request,
}) => {
  await registeredTargets(request);
  let failed = true,
    writes = 0;
  page.on("request", (request) => {
    if (
      new URL(request.url()).pathname.startsWith(endpoint) &&
      request.method() !== "GET"
    )
      writes++;
  });
  await page.route("**/api/v1/scenarios?*", (route) =>
    failed
      ? route.fulfill({
          status: 503,
          contentType: "application/json",
          body: JSON.stringify({
            code: "SCENARIO_STATE_UNAVAILABLE",
            message: "Injected initial read failure.",
          }),
        })
      : route.continue(),
  );
  await page.goto("/profiles");
  await expect(
    page.getByText(
      "The scenario library could not be read. Writes are disabled.",
      { exact: true },
    ),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "New scenario", exact: true }),
  ).toBeDisabled();
  await expect(
    page.getByText("No scenario definitions yet.", { exact: true }),
  ).toHaveCount(0);
  failed = false;
  await page.getByRole("button", { name: "Retry read", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "New scenario", exact: true }),
  ).toBeEnabled();
  expect(writes).toBe(0);
});

test("real scenario API preserves immutable revisions and exact target snapshots without execution", async ({
  request,
}) => {
  const initialResponse = await request.get(endpoint);
  expect(initialResponse.status()).toBe(200);
  const initial = await initialResponse.json();
  const { dut, sink } = await registeredTargets(request);
  const before = await (await request.get("/api/v1/workspace")).json();
  const input = definition(dut.id, sink.id);
  const createdResponse = await request.post(endpoint, {
    data: { revision: initial.revision, definition: input },
  });
  expect(createdResponse.status()).toBe(201);
  const created = await createdResponse.json();
  expect(created.revision).toBe(initial.revision + 1);
  expect(created.scenario.definition).toEqual(input);
  expect(created.scenario.version).toBe(1);
  expect(created.scenario.target_snapshot).toEqual(dut);
  expect(created.scenario.sink_snapshot).toEqual(sink);
  expect(created.execution_enabled).toBe(false);
  verifyDigest(created.scenario);

  const changed = {
    ...input,
    name: ` ${input.name} 🧪 `,
    objective: "  Literal whitespace\n새 정책의 기대 동작 확인\t ",
    policy_version: "fixture-policy-2",
    expected_action: "ALERT",
    delivery_expectation: "ALLOW",
    success_criteria: {
      minimum_delivery_pct: 95,
      maximum_delivery_pct: 100,
      detection_deadline_ms: 2000,
    },
  };
  const editedResponse = await request.put(
    `${endpoint}/${created.scenario.id}`,
    {
      data: { revision: created.revision, definition: changed },
    },
  );
  expect(editedResponse.status()).toBe(200);
  const edited = await editedResponse.json();
  expect(edited.scenario.id).toBe(created.scenario.id);
  expect(edited.scenario.version).toBe(2);
  expect(edited.scenario.definition).toEqual(changed);
  verifyDigest(edited.scenario);

  const stale = await request.put(`${endpoint}/${created.scenario.id}`, {
    data: { revision: created.revision, definition: input },
  });
  expect(stale.status()).toBe(409);
  expect((await stale.json()).code).toBe("SCENARIO_CONFLICT");
  const historyResponse = await request.get(
    `${endpoint}/${created.scenario.id}`,
  );
  expect(historyResponse.status()).toBe(200);
  const history = await historyResponse.json();
  expect(history.versions).toEqual([created.scenario, edited.scenario]);
  expect(history.revision).toBe(edited.revision);
  expect(await (await request.get("/api/v1/workspace")).json()).toEqual(before);

  for (const action of ["/api/v1/runs", "/api/v1/agent/execute"]) {
    const denied = await request.post(action, {
      data: { scenario_id: created.scenario.id, version: 2 },
    });
    expect(denied.status()).toBe(409);
  }
});

test("real scenario admission rejects malformed definitions and pagination without publishing", async ({
  request,
}) => {
  const initialResponse = await request.get(endpoint);
  expect(initialResponse.status()).toBe(200);
  const initial = await initialResponse.json();
  const { dut, sink } = await registeredTargets(request);
  const input = definition(dut.id, sink.id);
  for (const change of [
    { target_id: sink.id },
    { sink_id: dut.id },
    { delivery_expectation: "ALLOW" },
    { expected_action: "ALERT", detection_required: false },
    { profile_id: "tcpdump-observer" },
    { evidence_requirements: ["service_probe"] },
    { traffic_budget: { ...input.traffic_budget, duration_seconds: true } },
    { arbitrary_command: "must-never-execute" },
  ]) {
    const response = await request.post(endpoint, {
      data: { revision: initial.revision, definition: { ...input, ...change } },
    });
    expect(response.status()).toBe(422);
  }
  for (const query of [
    "limit=0",
    "offset=01",
    "limit=1&limit=2",
    "unexpected=1",
    "offset=1.0",
  ]) {
    expect((await request.get(`${endpoint}?${query}`)).status()).toBe(422);
  }
  expect(await (await request.get(endpoint)).json()).toEqual(initial);
});

for (const locale of ["en", "ko"] as const) {
  test(`real scenario form creates an exact persisted definition in ${locale}`, async ({
    page,
    request,
  }, testInfo) => {
    const { dut, sink } = await registeredTargets(request);
    const input = definition(dut.id, sink.id);
    const c = (en: string, ko: string) => (locale === "ko" ? ko : en);
    await page.addInitScript((language) => {
      localStorage.setItem("aegis.locale", language);
    }, locale);
    await page.setViewportSize({
      width: locale === "ko" ? 390 : 1440,
      height: 1000,
    });
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.goto("/profiles");
    const create = page.getByRole("button", {
      name: c("New scenario", "새 시나리오"),
      exact: true,
    });
    await expect(create).toBeEnabled();
    await create.click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    await dialog
      .getByLabel(c("Scenario name", "시나리오 이름"), { exact: true })
      .fill(input.name);
    await dialog
      .getByLabel(c("Objective", "목표"), { exact: true })
      .fill(input.objective);
    await dialog
      .getByLabel(c("DUT target", "DUT 대상"), { exact: true })
      .selectOption(dut.id);
    await dialog
      .getByLabel(c("Sink target", "수신 대상"), { exact: true })
      .selectOption(sink.id);
    await dialog
      .getByLabel(c("DUT version", "DUT 버전"), { exact: true })
      .fill(input.dut_version);
    await dialog
      .getByLabel(c("Policy version", "정책 버전"), { exact: true })
      .fill(input.policy_version);
    await dialog
      .getByLabel(c("Profile template", "프로필 템플릿"), { exact: true })
      .selectOption(input.profile_id);
    await dialog
      .getByLabel(c("Protocol", "프로토콜"), { exact: true })
      .selectOption(input.protocol);
    await dialog
      .getByLabel(c("IP version", "IP 버전"), { exact: true })
      .selectOption(String(input.ip_version));
    await dialog
      .getByLabel(c("Expected action", "기대 동작"), { exact: true })
      .selectOption(input.expected_action);
    await dialog
      .getByLabel(c("Delivery expectation", "전달 기대값"), { exact: true })
      .selectOption(input.delivery_expectation);
    await dialog
      .getByLabel(c("Detection required", "탐지 필수"), { exact: true })
      .check();

    const fields = [
      ["Maximum PPS", "최대 PPS", input.traffic_budget.max_pps],
      ["Maximum BPS", "최대 BPS", input.traffic_budget.max_bps],
      ["Maximum packets", "최대 패킷 수", input.traffic_budget.max_packets],
      ["Maximum bytes", "최대 바이트 수", input.traffic_budget.max_bytes],
      [
        "Maximum connections",
        "최대 연결 수",
        input.traffic_budget.max_connections,
      ],
      [
        "Duration (seconds)",
        "지속 시간(초)",
        input.traffic_budget.duration_seconds,
      ],
      [
        "Minimum delivery (%)",
        "최소 전달률(%)",
        input.success_criteria.minimum_delivery_pct,
      ],
      [
        "Maximum delivery (%)",
        "최대 전달률(%)",
        input.success_criteria.maximum_delivery_pct,
      ],
      [
        "Detection deadline (ms)",
        "탐지 제한 시간(ms)",
        input.success_criteria.detection_deadline_ms,
      ],
      [
        "Maximum legitimate loss (%)",
        "정상 트래픽 최대 손실률(%)",
        input.stop_conditions.max_legitimate_loss_pct,
      ],
      [
        "Maximum service latency (ms)",
        "최대 서비스 지연(ms)",
        input.stop_conditions.max_service_latency_ms,
      ],
    ] as const;
    for (const [en, ko, value] of fields) {
      await dialog.getByLabel(c(en, ko), { exact: true }).fill(String(value));
    }
    for (const [en, ko] of [
      ["Maximum CPU (%)", "최대 CPU 사용률(%)"],
      ["Maximum memory (%)", "최대 메모리 사용률(%)"],
      ["Maximum sessions", "최대 세션 수"],
    ]) {
      await dialog.getByLabel(c(en, ko), { exact: true }).fill("");
    }
    for (const [en, ko] of [
      ["Ingress PCAP", "앞단 PCAP"],
      ["Egress PCAP", "뒷단 PCAP"],
      ["DUT events", "DUT 이벤트"],
      ["Service probe", "정상 서비스 프로브"],
    ]) {
      await dialog.getByLabel(c(en, ko), { exact: true }).check();
    }
    await dialog
      .getByLabel(c("Resource metrics", "자원 메트릭"), { exact: true })
      .uncheck();

    const savedResponse = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === endpoint &&
        response.request().method() === "POST",
    );
    await dialog
      .getByRole("button", {
        name: c("Save scenario", "시나리오 저장"),
        exact: true,
      })
      .click();
    const response = await savedResponse;
    expect(response.status()).toBe(201);
    const receipt = await response.json();
    expect(receipt.scenario.definition).toEqual(input);
    verifyDigest(receipt.scenario);
    await expect(dialog).not.toBeVisible();
    await expect(
      page.getByText(input.name, { exact: true }).first(),
    ).toBeVisible();
    const card = page.locator(".scenario-list article").filter({
      has: page.getByRole("heading", { name: input.name, exact: true }),
    });
    await card
      .getByRole("button", {
        name: c("Scenario history", "시나리오 이력"),
        exact: true,
      })
      .click();
    const historyDialog = page.getByRole("dialog", {
      name: c("Scenario history", "시나리오 이력"),
      exact: true,
    });
    await expect(
      historyDialog.getByText(receipt.scenario.digest, { exact: true }),
    ).toBeVisible();
    await historyDialog
      .getByRole("button", {
        name: c("Edit scenario", "시나리오 수정"),
        exact: true,
      })
      .click();
    const editor = page.getByRole("dialog", {
      name: c("Edit scenario", "시나리오 수정"),
      exact: true,
    });
    await expect(editor).toBeVisible();
    await expect(
      editor.getByLabel(c("Scenario name", "시나리오 이름"), { exact: true }),
    ).toHaveValue(input.name);
    await page.setViewportSize({
      width: locale === "ko" ? 390 : 1024,
      height: 800,
    });
    await editor
      .getByLabel(c("Policy version", "정책 버전"), { exact: true })
      .fill("declared-policy-2");
    await editor
      .getByLabel(c("Declare PCAP identity", "PCAP 식별 정보 선언"), {
        exact: true,
      })
      .check();
    await editor
      .getByLabel(c("PCAP label", "PCAP 이름"), { exact: true })
      .fill(" Declared metadata 🧪 ");
    await editor
      .getByLabel("PCAP SHA256", { exact: true })
      .fill("b".repeat(64));
    await editor
      .getByLabel(c("PCAP size (bytes)", "PCAP 크기(바이트)"), { exact: true })
      .fill("1024");
    await editor
      .getByLabel(c("Maximum CPU (%)", "최대 CPU 사용률(%)"), { exact: true })
      .fill("90");
    await editor
      .getByLabel(c("Maximum memory (%)", "최대 메모리 사용률(%)"), {
        exact: true,
      })
      .fill("80");
    await editor
      .getByLabel(c("Maximum sessions", "최대 세션 수"), { exact: true })
      .fill("100");
    await editor
      .getByLabel(c("Resource metrics", "자원 메트릭"), { exact: true })
      .check();
    expect(
      await editor.evaluate((node) => {
        const box = node.getBoundingClientRect();
        return (
          box.left >= 0 &&
          box.right <= innerWidth &&
          box.top >= 0 &&
          box.bottom <= innerHeight &&
          node.scrollWidth <= node.clientWidth
        );
      }),
    ).toBe(true);
    const editedResponse = page.waitForResponse(
      (r) =>
        new URL(r.url()).pathname === `${endpoint}/${receipt.scenario.id}` &&
        r.request().method() === "PUT",
    );
    await editor
      .getByRole("button", {
        name: c("Save new version", "새 버전 저장"),
        exact: true,
      })
      .click();
    const editedWire = await editedResponse;
    expect(editedWire.status()).toBe(200);
    const edited = await editedWire.json();
    expect(edited.scenario.definition).toEqual({
      ...input,
      policy_version: "declared-policy-2",
      pcap_asset: {
        label: " Declared metadata 🧪 ",
        sha256: "b".repeat(64),
        size_bytes: 1024,
      },
      stop_conditions: {
        ...input.stop_conditions,
        max_cpu_pct: 90,
        max_memory_pct: 80,
        max_sessions: 100,
      },
      evidence_requirements: [
        ...input.evidence_requirements,
        "resource_metrics",
      ],
    });
    verifyDigest(edited.scenario);
    await expect(editor).not.toBeVisible();
    await card
      .getByRole("button", {
        name: c("Scenario history", "시나리오 이력"),
        exact: true,
      })
      .click();
    await historyDialog
      .getByLabel(c("Revision", "리비전"), { exact: true })
      .selectOption("1");
    await expect(
      historyDialog.getByText(receipt.scenario.digest, { exact: true }),
    ).toBeVisible();
    await expect(
      historyDialog.getByText(input.policy_version, { exact: true }),
    ).toBeVisible();
    await expect(
      historyDialog.getByRole("button", {
        name: c("Edit scenario", "시나리오 수정"),
        exact: true,
      }),
    ).toBeDisabled();
    const persistedHistory = await (
      await request.get(`${endpoint}/${receipt.scenario.id}`)
    ).json();
    expect(persistedHistory.versions).toEqual([
      receipt.scenario,
      edited.scenario,
    ]);
    await page.keyboard.press("Escape");
    await expect(historyDialog).not.toBeVisible();
    await expect(
      card.getByRole("button", {
        name: c("Scenario history", "시나리오 이력"),
        exact: true,
      }),
    ).toBeFocused();
    await page.reload();
    await expect(
      page.getByText(input.name, { exact: true }).first(),
    ).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
    expect(errors).toEqual([]);
    await page.screenshot({
      path: testInfo.outputPath(`scenario-${locale}.png`),
      fullPage: true,
    });
  });
}
