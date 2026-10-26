import { execFileSync } from "node:child_process";
import { resolve } from "node:path";
import { afterEach, expect, it, vi } from "vitest";
import { toolClient } from "./chat-tool-client";

// Real Python model serialization, scripted fetch only: NOT HTTP producer evidence.
const candidate = resolve(import.meta.dirname, "../../../..");
const produced: {
  bodies: Record<string, string>;
  variants: { label: string; name: string; raw: string }[];
  negatives: { name: string; path: string[]; raw: string }[];
} = JSON.parse(
  execFileSync(
    resolve(candidate, ".venv/bin/python"),
    ["-m", "tests.chat.scenario_model_wire"],
    {
      cwd: candidate,
      env: {
        ...process.env,
        PYTHONPATH: `${candidate}/src:${candidate}`,
        PYTHONDONTWRITEBYTECODE: "1",
        PYTHONNOUSERSITE: "1",
      },
      encoding: "utf8",
      timeout: 30000,
    },
  ),
);
const raw = (name: string) => produced.bodies[name];
const value = (name: string) => JSON.parse(raw(name));
function response(body: string, status = 200) {
  return new Response(body, {
    status,
    headers: { "content-type": "application/json" },
  });
}
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  vi.useRealTimers();
});

import type { ScenarioGrantCommitment } from "./chat-scenario-wire";
import { session as oldSession, turn as oldTurn } from "./chat-test-fixtures";
import type { GrantV4 } from "./chat-scenario-types";
function commitment(): ScenarioGrantCommitment {
  const g = value("GrantV4");
  return {
    requestedAuthority: "scenario_write_v4",
    request: value("GrantInputV4"),
    settings_revision: g.settings_revision,
    profile_id: g.profile_id,
    resolved_inputs: g.resolved_inputs,
  };
}
function sessionFor(c: ScenarioGrantCommitment) {
  return {
    ...oldSession,
    schema_version: 1 as const,
    locale: "en" as const,
    id: c.request.session_id,
    sequence: c.request.expected_sequence,
    settings_revision: c.settings_revision,
    profile_id: c.profile_id,
  };
}
function grantFor(c: ScenarioGrantCommitment) {
  return toolClient.grant(
    sessionFor(c),
    c.request.request_id,
    c.request.turn_request_id,
    c.request.text,
    c,
  );
}
it("v4 grant sends the full literal request and binds model-produced ACK", async () => {
  const c = commitment();
  const fetcher = vi.fn().mockResolvedValue(response(raw("GrantV4"), 201));
  vi.stubGlobal("fetch", fetcher);
  expect(await grantFor(c)).toEqual(value("GrantV4"));
  expect(JSON.parse(fetcher.mock.calls[0][1].body)).toEqual(c.request);
  expect(fetcher).toHaveBeenCalledTimes(1);
});
it("captures nested commitment before await and uses only GET after lost ACK", async () => {
  const c = commitment(),
    original = structuredClone(c);
  const fetcher = vi.fn(async (_url: string, init: RequestInit) => {
    if (init.method === "POST") throw Error("lost");
    return response(raw("GrantV4"));
  });
  vi.stubGlobal("fetch", fetcher);
  const pending = grantFor(c);
  c.request.intent.input_source = {
    source: "scenario_version",
    reference: { id: "foreign", version: 1, digest: "f".repeat(64) },
  };
  c.resolved_inputs.traffic_budget.max_pps = 88;
  c.settings_revision = 99;
  expect(await pending).toEqual(value("GrantV4"));
  expect(fetcher.mock.calls.map(([url, init]) => [url, init.method])).toEqual([
    ["/api/v1/chat/tool-grants", "POST"],
    [
      `/api/v1/chat/tool-grants/by-request/${original.request.request_id}`,
      "GET",
    ],
  ]);
  expect(JSON.parse(fetcher.mock.calls[0][1].body as string)).toEqual(
    original.request,
  );
});
it("v4 submit snapshots grant/session/commitment before binding and recovers only the exact turn", async () => {
  const c = commitment(),
    original = structuredClone(c),
    s = sessionFor(c),
    g: GrantV4 = value("GrantV4");
  const turn = {
    ...oldTurn,
    session_id: s.id,
    request_id: c.request.turn_request_id,
    sequence: 1,
    user_text: c.request.text,
  };
  const fetcher = vi.fn(async (_url: string, init: RequestInit) => {
    if (init.method === "POST") throw Error("lost");
    return response(JSON.stringify(turn));
  });
  vi.stubGlobal("fetch", fetcher);
  const pending = toolClient.submit(s, g, c.request.text, () => true, c);
  c.request.text = "changed";
  c.resolved_inputs.traffic_budget.max_pps = 99;
  s.sequence = 11;
  g.id = oldTurn.id;
  expect(await pending).toEqual(turn);
  expect(JSON.parse(fetcher.mock.calls[0][1].body as string)).toEqual({
    request_id: original.request.turn_request_id,
    expected_sequence: 0,
    text: original.request.text,
    grant_id: value("GrantV4").id,
  });
  expect(fetcher.mock.calls.map(([, init]) => init.method)).toEqual([
    "POST",
    "GET",
  ]);
});

import * as toolWire from "./chat-tool-wire";
it.each([32768, 32769])(
  "runtime raw cap counts whitespace at %i bytes",
  async (size) => {
    const body = raw("RuntimeV4"),
      padded = body + " ".repeat(size - new TextEncoder().encode(body).length);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(padded)));
    if (size === 32768)
      expect(await toolClient.runtime()).toEqual(value("RuntimeV4"));
    else await expect(toolClient.runtime()).rejects.toThrow();
  },
);
it.each([9999, 10000, 10001])(
  "original monotonic deadline covers awaited codec publication at %i ms",
  async (elapsed) => {
    let clock = 0;
    vi.spyOn(performance, "now").mockImplementation(() => clock);
    const parse = toolWire.parseToolRuntimeResponse;
    vi.spyOn(toolWire, "parseToolRuntimeResponse").mockImplementation(
      async (v) => {
        const result = await parse(v);
        clock = elapsed;
        return result;
      },
    );
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(response(raw("RuntimeV4"))),
    );
    if (elapsed < 10000)
      expect(await toolClient.runtime()).toEqual(value("RuntimeV4"));
    else await expect(toolClient.runtime()).rejects.toThrow();
  },
);
it("deadline cancels a blocked raw reader, rejects without publication and cleans timer/listener", async () => {
  vi.useFakeTimers();
  const cancelled = vi.fn(),
    signal = new AbortController().signal;
  const add = vi.spyOn(signal, "addEventListener"),
    remove = vi.spyOn(signal, "removeEventListener");
  const body = new ReadableStream<Uint8Array>({ cancel: cancelled });
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValue(
        new Response(body, { headers: { "content-type": "application/json" } }),
      ),
  );
  const result = toolClient.runtime(signal).then(
    () => "published",
    () => "rejected",
  );
  await vi.advanceTimersByTimeAsync(10000);
  expect(cancelled).toHaveBeenCalledTimes(1);
  expect(await result).toBe("rejected");
  expect(vi.getTimerCount()).toBe(0);
  expect(remove.mock.calls[0][1]).toBe(add.mock.calls[0][1]);
});

it("cold v4 transcript needs only literal turn ID, never unavailable historical grant metadata", async () => {
  const t = value("TranscriptV4");
  const fetcher = vi.fn(async (url: string) => {
    expect(url).toBe(`/api/v1/chat/turns/${t.turn_id}/tools`);
    return response(raw("TranscriptV4"));
  });
  vi.stubGlobal("fetch", fetcher);
  expect(await toolClient.tools(t.turn_id)).toEqual(t);
  expect(fetcher).toHaveBeenCalledTimes(1);
});
it("live v4 transcript additionally binds every call to captured authority and original deadline", async () => {
  const t = value("TranscriptV4"),
    g: GrantV4 = value("GrantV4");
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => response(raw("TranscriptV4"))),
  );
  expect(
    await toolClient.tools(t.turn_id, undefined, {
      grant: g,
      deadlineAt: "2026-01-01T00:02:00Z",
    }),
  ).toEqual(t);
  g.intent.expected_draft_revision++;
  await expect(
    toolClient.tools(t.turn_id, undefined, {
      grant: g,
      deadlineAt: "2026-01-01T00:02:00Z",
    }),
  ).rejects.toThrow();
});
it("v4 reconciliation carries both revisions and does not recover scenario quarantine", async () => {
  const fence = {
    schema_version: 1 as const,
    generation: 0,
    fenced: true,
    call_ids: [value("CallV4").id],
    current_draft_revision: 0,
  };
  const state = {
    ...value("ScenarioStateInspection"),
    registry_write_status: "quarantined" as const,
  };
  const fetcher = vi.fn<typeof fetch>(async () =>
    response(raw("ReconcileReceiptV4"), 201),
  );
  vi.stubGlobal("fetch", fetcher);
  const receipt = await toolClient.reconcile(
    value("ReconcileInputV4").request_id,
    fence,
    state,
  );
  expect(receipt).toEqual(value("ReconcileReceiptV4"));
  expect(JSON.parse(fetcher.mock.calls[0][1]!.body as string)).toEqual(
    value("ReconcileInputV4"),
  );
  expect(state.registry_write_status).toBe("quarantined");
  expect(fetcher).toHaveBeenCalledTimes(1);
});

import * as scenarioWire from "./chat-scenario-wire";
import { ChatRequestError } from "./chat-client";
it("grant ACK and GET recovery bind within the transport codec deadline", async () => {
  let clock = 0;
  vi.spyOn(performance, "now").mockImplementation(() => clock);
  const bind = scenarioWire.boundGrant;
  vi.spyOn(scenarioWire, "boundGrant").mockImplementation(async (v, c) => {
    const result = await bind(v, c);
    clock += 10001;
    return result;
  });
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_url: string, init: RequestInit) =>
      response(raw("GrantV4"), init.method === "POST" ? 201 : 200),
    ),
  );
  await expect(grantFor(commitment())).rejects.toThrow();
});
it("new scenario quarantine code maps only the exact 409 closed error and never resends grant", async () => {
  const fetcher = vi.fn(async () =>
    response(
      JSON.stringify({
        code: "CHAT_SCENARIO_WRITE_FENCED",
        message:
          "Scenario storage is write-quarantined. Chat acknowledgement does not recover it; follow offline scenario recovery.",
      }),
      409,
    ),
  );
  vi.stubGlobal("fetch", fetcher);
  await expect(grantFor(commitment())).rejects.toMatchObject({
    code: "CHAT_SCENARIO_WRITE_FENCED",
    definite: true,
  });
  expect(fetcher).toHaveBeenCalledTimes(1);
});
it("metadata retries typed CHAT_BUSY at most three times, spaced after response completion", async () => {
  vi.useFakeTimers();
  const fetcher = vi.fn(async () =>
    response(JSON.stringify({ code: "CHAT_BUSY", message: "busy" }), 409),
  );
  vi.stubGlobal("fetch", fetcher);
  const result = readChatMetadata(
    toolClient.runtime,
    new AbortController().signal,
  ).catch((error: unknown) => error);
  await vi.advanceTimersByTimeAsync(499);
  expect(fetcher).toHaveBeenCalledTimes(1);
  await vi.advanceTimersByTimeAsync(1);
  expect(fetcher).toHaveBeenCalledTimes(2);
  await vi.advanceTimersByTimeAsync(499);
  expect(fetcher).toHaveBeenCalledTimes(2);
  await vi.advanceTimersByTimeAsync(1);
  expect(fetcher).toHaveBeenCalledTimes(3);
  expect(await result).toBeInstanceOf(ChatRequestError);
  expect(vi.getTimerCount()).toBe(0);
});
it("scenario inspection serializes fence/state/history/state/fence and retains quarantine", async () => {
  const fence = {
    schema_version: 1,
    generation: 0,
    fenced: true,
    call_ids: [value("CallV4").id],
    current_draft_revision: 0,
  };
  const state = {
    ...value("ScenarioStateInspection"),
    registry_write_status: "quarantined",
    scenario_revision: 2,
  };
  const paths: string[] = [],
    bodies = [
      JSON.stringify(fence),
      JSON.stringify(state),
      raw("ScenarioHistoryV4"),
      JSON.stringify(state),
      JSON.stringify(fence),
    ];
  const fetcher = vi.fn(async (url: string) => {
    paths.push(url);
    return response(bodies.shift()!);
  });
  vi.stubGlobal("fetch", fetcher);
  const inspected = await toolClient.inspectScenario("legacy-scenario");
  expect(inspected.history).toEqual(value("ScenarioHistoryV4"));
  expect(inspected.state.registry_write_status).toBe("quarantined");
  expect(paths).toEqual([
    "/api/v1/chat/tools/fence",
    "/api/v1/chat/tools/scenarios/state",
    "/api/v1/scenarios/legacy-scenario",
    "/api/v1/chat/tools/scenarios/state",
    "/api/v1/chat/tools/fence",
  ]);
});

it("revoke supports a captured v4 grant and compares every immutable field", async () => {
  const g: GrantV4 = value("GrantV4");
  const revoked = structuredClone({ ...g, status: "revoked" });
  const fetcher = vi.fn(async () => response(JSON.stringify(revoked)));
  vi.stubGlobal("fetch", fetcher);
  const pending = toolClient.revoke(g);
  g.intent.expected_draft_revision = 99;
  expect(await pending).toEqual(revoked);
  expect(fetcher).toHaveBeenCalledTimes(1);
});
it("unknown-ID inspection reads only the explicit page between serial metadata observations", async () => {
  const fence = {
    schema_version: 1,
    generation: 0,
    fenced: true,
    call_ids: [value("CallV4").id],
    current_draft_revision: 0,
  };
  const state = { ...value("ScenarioStateInspection"), scenario_revision: 2 };
  const bodies = [
    JSON.stringify(fence),
    JSON.stringify(state),
    raw("ScenarioPageV4"),
    JSON.stringify(state),
    JSON.stringify(fence),
  ];
  const fetcher = vi.fn(async () => response(bodies.shift()!));
  vi.stubGlobal("fetch", fetcher);
  const inspected = await toolClient.inspectScenarioPage();
  expect(inspected.page).toEqual(value("ScenarioPageV4"));
  expect(fetcher).toHaveBeenNthCalledWith(
    3,
    "/api/v1/scenarios?offset=0&limit=50",
    expect.anything(),
  );
  expect(fetcher).toHaveBeenCalledTimes(5);
});

it.each([32768, 32769])(
  "decision companion uses fixed raw cap %i without write retry",
  async (size) => {
    const d = value("Decision"),
      body = raw("Decision");
    const fetcher = vi.fn(async () =>
      response(
        body + " ".repeat(size - new TextEncoder().encode(body).length),
        201,
      ),
    );
    vi.stubGlobal("fetch", fetcher);
    const pending = toolClient.decide(
      d.call_id,
      value("TranscriptV4").turn_id,
      value("DecisionInput"),
      false,
    );
    if (size === 32768) expect(await pending).toEqual(d);
    else await expect(pending).rejects.toThrow();
    expect(fetcher).toHaveBeenCalledTimes(1);
  },
);

it.each(produced.variants.filter((v) => v.name === "CallV4"))(
  "cold transcript dispatch accepts model-serialized $label",
  async (entry) => {
    const t = value("TranscriptV4");
    // Envelope assembly is synthetic; the nested call is actual model output.
    const body = `{"schema_version":4,"turn_id":${JSON.stringify(t.turn_id)},"revision":1,"calls":[${entry.raw}]}`;
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => response(body)),
    );
    expect((await toolClient.tools(t.turn_id)).calls).toEqual([
      JSON.parse(entry.raw),
    ]);
  },
);
it.each(
  produced.negatives.filter((v) =>
    ["RuntimeV4", "GrantV4", "CallV4", "TranscriptV4"].includes(v.name),
  ),
)(
  "transport permanently refuses model-derived invalid $name $path",
  async (entry) => {
    const t = value("TranscriptV4");
    const body =
      entry.name === "CallV4"
        ? `{"schema_version":4,"turn_id":${JSON.stringify(t.turn_id)},"revision":1,"calls":[${entry.raw}]}`
        : entry.raw;
    const fetcher = vi.fn(async () => response(body));
    vi.stubGlobal("fetch", fetcher);
    if (entry.name === "RuntimeV4")
      await expect(toolClient.runtime()).rejects.toThrow();
    else if (entry.name === "GrantV4")
      await expect(grantFor(commitment())).rejects.toThrow();
    else await expect(toolClient.tools(t.turn_id)).rejects.toThrow();
    expect(fetcher.mock.calls.length).toBeLessThanOrEqual(
      entry.name === "GrantV4" ? 2 : 1,
    );
  },
);
it.each([
  "settings",
  "profile",
  "draft-revision",
  "scenario-revision",
  "text",
  "source",
  "resolved",
])("grant GET-only recovery rejects captured %s mismatch", async (field) => {
  const c = commitment();
  if (field === "settings") c.settings_revision++;
  if (field === "profile") c.profile_id = "other";
  if (field === "draft-revision") c.request.intent.expected_draft_revision++;
  if (field === "scenario-revision")
    c.request.intent.expected_scenario_revision++;
  if (field === "text") c.request.text += " changed";
  if (field === "source")
    c.request.intent.input_source = {
      source: "scenario_version",
      reference: value("ScenarioRef"),
    };
  if (field === "resolved") {
    c.resolved_inputs.traffic_budget.max_pps++;
    c.request.intent.input_source = {
      source: "operator",
      inputs: structuredClone(c.resolved_inputs),
    };
  }
  const fetcher = vi.fn(async () => response(raw("GrantV4")));
  vi.stubGlobal("fetch", fetcher);
  await expect(
    toolClient.recoverGrant(
      sessionFor(c),
      c.request.request_id,
      c.request.turn_request_id,
      c.request.text,
      c,
    ),
  ).rejects.toThrow();
  expect(fetcher).toHaveBeenCalledExactlyOnceWith(
    `/api/v1/chat/tool-grants/by-request/${c.request.request_id}`,
    expect.objectContaining({ method: "GET" }),
  );
});
it("version source commitment uses captured projection with no current-source fetch", async () => {
  const entry = produced.variants.find((v) => v.label === "version-source")!,
    g: GrantV4 = JSON.parse(entry.raw),
    c = commitment();
  c.request.intent = structuredClone(g.intent);
  c.resolved_inputs = structuredClone(g.resolved_inputs);
  const fetcher = vi.fn<typeof fetch>(async () => response(entry.raw));
  vi.stubGlobal("fetch", fetcher);
  expect(await grantFor(c)).toEqual(g);
  expect(fetcher).toHaveBeenCalledTimes(1);
  if (c.request.intent.input_source.source !== "scenario_version")
    throw Error("fixture");
  c.request.intent.input_source.reference.digest = "f".repeat(64);
  await expect(grantFor(c)).rejects.toThrow();
  expect(
    fetcher.mock.calls.every(
      ([url]) => typeof url === "string" && url.includes("tool-grants"),
    ),
  ).toBe(true);
});
it.each(["1", "2", "3", '"4"', "4.0", "4e0", "true"])(
  "v4 grant cannot fall back to schema token %s",
  async (token) => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        response(
          raw("GrantV4").replace(
            '"schema_version":4',
            `"schema_version":${token}`,
          ),
        ),
      ),
    );
    await expect(grantFor(commitment())).rejects.toThrow();
  },
);
it("contradictory decoded ACK remains refusal even when GET readback matches", async () => {
  const foreign = { ...value("GrantV4"), settings_revision: 7 };
  const fetcher = vi.fn(async (_url: string, init: RequestInit) =>
    response(
      init.method === "POST" ? JSON.stringify(foreign) : raw("GrantV4"),
      init.method === "POST" ? 201 : 200,
    ),
  );
  vi.stubGlobal("fetch", fetcher);
  await expect(grantFor(commitment())).rejects.toThrow();
  expect(fetcher.mock.calls.map(([, init]) => init.method)).toEqual([
    "POST",
    "GET",
  ]);
});
it("submit does not dispatch without captured v4 authority or after last-moment admission loss", async () => {
  const c = commitment(),
    g: GrantV4 = value("GrantV4"),
    fetcher = vi.fn();
  vi.stubGlobal("fetch", fetcher);
  await expect(
    toolClient.submit(sessionFor(c), g, c.request.text),
  ).rejects.toThrow();
  await expect(
    toolClient.submit(sessionFor(c), g, c.request.text, () => false, c),
  ).rejects.toThrow();
  expect(fetcher).not.toHaveBeenCalled();
});
it.each(["CHAT_STORAGE_ERROR", "CHAT_NOT_FOUND", "CHAT_TIMEOUT"])(
  "metadata %s is unavailable, never retried or replaced with revision zero",
  async (code) => {
    const fetcher = vi.fn(async () =>
      response(JSON.stringify({ code, message: "unavailable" }), 503),
    );
    vi.stubGlobal("fetch", fetcher);
    await expect(toolClient.scenarioState()).rejects.toBeInstanceOf(
      ChatRequestError,
    );
    expect(fetcher).toHaveBeenCalledTimes(1);
  },
);
it.each(["generation", "draft", "registry", "status"])(
  "serial inspection denies changed %s observation",
  async (field) => {
    const f = {
      schema_version: 1,
      generation: 0,
      fenced: true,
      call_ids: [value("CallV4").id],
      current_draft_revision: 0,
    };
    const s = { ...value("ScenarioStateInspection"), scenario_revision: 2 },
      afterF = structuredClone(f),
      afterS = structuredClone(s);
    if (field === "generation") afterF.generation++;
    if (field === "draft") afterF.current_draft_revision++;
    if (field === "registry") afterS.scenario_revision++;
    if (field === "status") afterS.registry_write_status = "quarantined";
    const bodies = [
      JSON.stringify(f),
      JSON.stringify(s),
      raw("ScenarioHistoryV4"),
      JSON.stringify(afterS),
      JSON.stringify(afterF),
    ];
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => response(bodies.shift()!)),
    );
    await expect(
      toolClient.inspectScenario("legacy-scenario"),
    ).rejects.toThrow();
  },
);
it.each([9999, 10000, 10001])(
  "blocked read completion at %i ms uses original clock and cleans up",
  async (elapsed) => {
    let clock = 0,
      release!: () => void,
      entered!: () => void;
    const started = new Promise<void>((resolve) => {
      entered = resolve;
    });
    vi.spyOn(performance, "now").mockImplementation(() => clock);
    const cancelled = vi.fn();
    const stream = new ReadableStream<Uint8Array>(
      {
        start(controller) {
          release = () => {
            controller.enqueue(new TextEncoder().encode(raw("RuntimeV4")));
            controller.close();
          };
        },
        pull() {
          entered();
        },
        cancel: cancelled,
      },
      { highWaterMark: 0 },
    );
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(stream, {
            headers: { "content-type": "application/json" },
          }),
      ),
    );
    const pending = toolClient.runtime();
    await started;
    clock = elapsed;
    release();
    if (elapsed < 10000) expect(await pending).toEqual(value("RuntimeV4"));
    else await expect(pending).rejects.toThrow();
    expect(stream.locked).toBe(false);
  },
);
it("abort during async codec rejects early and cannot publish its later success", async () => {
  let release!: () => void, entered!: () => void;
  const started = new Promise<void>((resolve) => {
    entered = resolve;
  });
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  const parse = toolWire.parseToolRuntimeResponse;
  vi.spyOn(toolWire, "parseToolRuntimeResponse").mockImplementation(
    async (v) => {
      entered();
      await held;
      return parse(v);
    },
  );
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => response(raw("RuntimeV4"))),
  );
  const controller = new AbortController();
  const published = vi.fn();
  const result = toolClient
    .runtime(controller.signal)
    .then(published, () => "aborted");
  await started;
  controller.abort();
  expect(await result).toBe("aborted");
  release();
  await Promise.resolve();
  expect(published).not.toHaveBeenCalled();
});
it.each([
  "duplicate",
  "alias",
  "depth33",
  "float",
  "exponent",
  "surrogate",
  "bom",
  "utf8",
])("raw companion rejects %s before capability publication", async (kind) => {
  let body: string | Uint8Array<ArrayBuffer> = raw("RuntimeV4");
  if (kind === "duplicate")
    body = body.replace(
      '"schema_version":4',
      '"schema_version":4,"schema_version":4',
    );
  if (kind === "alias")
    body = body.replace(
      '"schema_version":4',
      '"schema_version":4,"schema_\\u0076ersion":4',
    );
  if (kind === "depth33") body = "[".repeat(33) + "0" + "]".repeat(33);
  if (kind === "float")
    body = body.replace('"schema_version":4', '"schema_version":4.0');
  if (kind === "exponent")
    body = body.replace('"schema_version":4', '"schema_version":4e0');
  if (kind === "surrogate")
    body = body.replace('"reason":null', '"reason":"\\ud800"');
  if (kind === "bom") body = "\uFEFF" + body;
  if (kind === "utf8") body = new Uint8Array([0xc0, 0xaf]);
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(body, { headers: { "content-type": "application/json" } }),
    ),
  );
  await expect(toolClient.runtime()).rejects.toThrow();
});
it.each([1048576, 1048577])(
  "transcript raw UTF8 cap %i is not canonical-size-only",
  async (size) => {
    const body = raw("TranscriptV4");
    const padded =
      body + " ".repeat(size - new TextEncoder().encode(body).length);
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => response(padded)),
    );
    const pending = toolClient.tools(value("TranscriptV4").turn_id);
    if (size === 1048576) expect(await pending).toEqual(value("TranscriptV4"));
    else await expect(pending).rejects.toThrow();
  },
);

it("append commits exact latest base separately from older selected source; all base fields are bound", async () => {
  const pair: { request: string; grant: string } = JSON.parse(
    execFileSync(
      resolve(candidate, ".venv/bin/python"),
      [
        "-c",
        "import json\nfrom aiddos.api import chat_scenario_models as m\nfrom tests.chat.test_chat_scenario_models import grant, grant_input\nfrom tests.chat.scenario_model_wire import record\nr=grant_input(); g=grant()\nbase=m.scenario_ref(record(version=2)); source=m.scenario_ref(record(version=1))\nr['intent'].update(operation='scenario_append', expected_scenario_revision=2, base=base, input_source={'source':'scenario_version','reference':source})\ng.update(intent=r['intent'],proposal_tools=['scenario_append'])\ng['inputs_digest']=m.inputs_digest(g['intent']['input_source'],g['resolved_inputs'])\nprint(json.dumps({'request':m.GrantInputV4.model_validate(r).model_dump_json(),'grant':m.GrantV4.model_validate(g).model_dump_json()}))\n",
      ],
      {
        cwd: candidate,
        env: {
          ...process.env,
          PYTHONPATH: `${candidate}/src:${candidate}`,
          PYTHONDONTWRITEBYTECODE: "1",
          PYTHONNOUSERSITE: "1",
        },
        encoding: "utf8",
        timeout: 30000,
      },
    ),
  );
  const g: GrantV4 = JSON.parse(pair.grant);
  const c: ScenarioGrantCommitment = {
    requestedAuthority: "scenario_write_v4",
    request: JSON.parse(pair.request),
    settings_revision: g.settings_revision,
    profile_id: g.profile_id,
    resolved_inputs: structuredClone(g.resolved_inputs),
  };
  const fetcher = vi.fn<typeof fetch>(async () => response(pair.grant));
  vi.stubGlobal("fetch", fetcher);
  expect(await grantFor(c)).toEqual(g);
  expect(JSON.parse(fetcher.mock.calls[0][1]!.body as string)).toEqual(
    JSON.parse(pair.request),
  );
  for (const key of ["id", "version", "digest"] as const) {
    const changed = structuredClone(c);
    if (!changed.request.intent.base) throw Error("fixture");
    if (key === "id") changed.request.intent.base.id = "foreign";
    if (key === "version") changed.request.intent.base.version = 1;
    if (key === "digest") changed.request.intent.base.digest = "f".repeat(64);
    await expect(
      toolClient.recoverGrant(
        sessionFor(changed),
        changed.request.request_id,
        changed.request.turn_request_id,
        changed.request.text,
        changed,
      ),
    ).rejects.toThrow();
  }
});

it.each([
  "media",
  "status",
  "length",
  "error-cap",
  "extra-error",
  "unknown-code",
  "wrong-fenced-status",
  "wrong-fenced-message",
])(
  "closed transport boundary refuses %s without metadata retry",
  async (kind) => {
    const message =
      "Scenario storage is write-quarantined. Chat acknowledgement does not recover it; follow offline scenario recovery.";
    let body = raw("RuntimeV4"),
      status = 200;
    const headers: Record<string, string> = {
      "content-type": "application/json",
    };
    if (kind === "media") headers["content-type"] = "text/plain";
    if (kind === "status") status = 201;
    if (kind === "length") headers["content-length"] = "32769";
    if (kind === "error-cap") {
      status = 409;
      body = JSON.stringify({ code: "CHAT_BUSY", message: "x".repeat(32769) });
    }
    if (kind === "extra-error") {
      status = 409;
      body = JSON.stringify({ code: "CHAT_BUSY", message: "busy", extra: 1 });
    }
    if (kind === "unknown-code") {
      status = 409;
      body = JSON.stringify({ code: "CHAT_SCENARIO_FENCED", message });
    }
    if (kind === "wrong-fenced-status") {
      status = 503;
      body = JSON.stringify({ code: "CHAT_SCENARIO_WRITE_FENCED", message });
    }
    if (kind === "wrong-fenced-message") {
      status = 409;
      body = JSON.stringify({
        code: "CHAT_SCENARIO_WRITE_FENCED",
        message: "wrong",
      });
    }
    const fetcher = vi.fn(async () => new Response(body, { status, headers }));
    vi.stubGlobal("fetch", fetcher);
    await expect(toolClient.runtime()).rejects.toThrow();
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(fetcher).toHaveBeenCalledWith(
      "/api/v1/chat/tools/runtime",
      expect.objectContaining({ cache: "no-store", redirect: "error" }),
    );
  },
);
it("cancel during busy spacing clears timer and prevents the next metadata request", async () => {
  vi.useFakeTimers();
  const controller = new AbortController(),
    fetcher = vi.fn(async () =>
      response(JSON.stringify({ code: "CHAT_BUSY", message: "busy" }), 409),
    );
  vi.stubGlobal("fetch", fetcher);
  const result = readChatMetadata(
    toolClient.scenarioState,
    controller.signal,
  ).catch(() => "aborted");
  await vi.advanceTimersByTimeAsync(499);
  controller.abort();
  expect(await result).toBe("aborted");
  await vi.advanceTimersByTimeAsync(1000);
  expect(fetcher).toHaveBeenCalledTimes(1);
  expect(vi.getTimerCount()).toBe(0);
});
it("busy grant and reconcile writes are never retried", async () => {
  const fetcher = vi.fn(async () =>
    response(JSON.stringify({ code: "CHAT_BUSY", message: "busy" }), 409),
  );
  vi.stubGlobal("fetch", fetcher);
  await expect(grantFor(commitment())).rejects.toBeInstanceOf(ChatRequestError);
  expect(fetcher).toHaveBeenCalledTimes(1);
  const fence = {
    schema_version: 1 as const,
    generation: 0,
    fenced: true,
    call_ids: [value("CallV4").id],
    current_draft_revision: 0,
  };
  await expect(
    toolClient.reconcile(
      value("ReconcileInputV4").request_id,
      fence,
      value("ScenarioStateInspection"),
    ),
  ).rejects.toBeInstanceOf(ChatRequestError);
  expect(fetcher).toHaveBeenCalledTimes(2);
});
it("lost decision ACK recovers only our exact receipt from v4 history; it is not Saved", async () => {
  const d = value("Decision");
  const fetcher = vi.fn(async (_url: string, init: RequestInit) => {
    if (init.method === "POST") throw Error("lost ACK");
    return response(raw("TranscriptV4"));
  });
  vi.stubGlobal("fetch", fetcher);
  expect(
    await toolClient.decide(
      d.call_id,
      value("TranscriptV4").turn_id,
      value("DecisionInput"),
    ),
  ).toEqual(d);
  expect(fetcher.mock.calls.map(([, init]) => init.method)).toEqual([
    "POST",
    "GET",
  ]);
  const wrong = { ...value("DecisionInput"), request_id: value("GrantV4").id };
  await expect(
    toolClient.decide(d.call_id, value("TranscriptV4").turn_id, wrong),
  ).rejects.toThrow();
});
it.each(["request", "generation", "ids", "revision", "recovery", "schema"])(
  "v4 reconcile refuses contradictory %s receipt without retries",
  async (field) => {
    const receipt = value("ReconcileReceiptV4");
    if (field === "request") receipt.request_id = value("GrantV4").id;
    if (field === "generation") receipt.generation++;
    if (field === "ids") receipt.acknowledged_call_ids = [value("GrantV4").id];
    if (field === "revision") receipt.observed_scenario_revision++;
    if (field === "recovery") receipt.scenario_recovery = "performed";
    if (field === "schema") receipt.schema_version = 1;
    const fetcher = vi.fn(async () => response(JSON.stringify(receipt), 201));
    vi.stubGlobal("fetch", fetcher);
    const fence = {
      schema_version: 1 as const,
      generation: 0,
      fenced: true,
      call_ids: [value("CallV4").id],
      current_draft_revision: 0,
    };
    await expect(
      toolClient.reconcile(
        value("ReconcileInputV4").request_id,
        fence,
        value("ScenarioStateInspection"),
      ),
    ).rejects.toThrow();
    expect(fetcher).toHaveBeenCalledTimes(1);
  },
);

import { readChatMetadata } from "./chat-metadata";
it("retained UI metadata composition never multiplies the three-attempt budget", async () => {
  vi.useFakeTimers();
  const fetcher = vi.fn(async () =>
    response(JSON.stringify({ code: "CHAT_BUSY", message: "busy" }), 409),
  );
  vi.stubGlobal("fetch", fetcher);
  const result = readChatMetadata(
    toolClient.runtime,
    new AbortController().signal,
  ).catch((error: unknown) => error);
  await vi.advanceTimersByTimeAsync(10000);
  expect(fetcher).toHaveBeenCalledTimes(3);
  expect(await result).toBeInstanceOf(ChatRequestError);
  expect(vi.getTimerCount()).toBe(0);
});

it("late fulfilled fetch cancels its unread body even when the timer has not run", async () => {
  let clock = 0;
  vi.spyOn(performance, "now").mockImplementation(() => clock);
  const cancelled = vi.fn();
  const stream = new ReadableStream<Uint8Array>({ cancel: cancelled });
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => {
      clock = 10001;
      return new Response(stream, {
        headers: { "content-type": "application/json" },
      });
    }),
  );
  await expect(toolClient.runtime()).rejects.toThrow();
  expect(cancelled).toHaveBeenCalledTimes(1);
  expect(stream.locked).toBe(false);
});

it("caller cancellation retains a pending fetch slot until retirement, but never publishes", async () => {
  vi.useFakeTimers();
  let release!: (response: Response) => void;
  const fetcher = vi.fn(
    () =>
      new Promise<Response>((resolve) => {
        release = resolve;
      }),
  );
  vi.stubGlobal("fetch", fetcher);
  const controller = new AbortController();
  let settled = false;
  const result = toolClient
    .tools(value("TranscriptV4").turn_id, controller.signal)
    .then(
      () => {
        settled = true;
        return "published";
      },
      () => {
        settled = true;
        return "rejected";
      },
    );
  controller.abort();
  await vi.advanceTimersByTimeAsync(500);
  expect(settled).toBe(false);
  const cancelled = vi.fn();
  release(
    new Response(new ReadableStream({ cancel: cancelled }), {
      headers: { "content-type": "application/json" },
    }),
  );
  expect(await result).toBe("rejected");
  expect(cancelled).toHaveBeenCalledTimes(1);
  expect(vi.getTimerCount()).toBe(0);
});
it("hard deadline still bounds fetch ignoring caller abort and cancels its late body", async () => {
  vi.useFakeTimers();
  let release!: (response: Response) => void;
  vi.stubGlobal(
    "fetch",
    vi.fn(
      () =>
        new Promise<Response>((resolve) => {
          release = resolve;
        }),
    ),
  );
  const controller = new AbortController();
  const result = toolClient.runtime(controller.signal).then(
    () => "published",
    () => "rejected",
  );
  controller.abort();
  await vi.advanceTimersByTimeAsync(10000);
  expect(await result).toBe("rejected");
  const cancelled = vi.fn();
  release(
    new Response(new ReadableStream({ cancel: cancelled }), {
      headers: { "content-type": "application/json" },
    }),
  );
  await vi.advanceTimersByTimeAsync(0);
  expect(cancelled).toHaveBeenCalledTimes(1);
  expect(vi.getTimerCount()).toBe(0);
});

it("actual tool runtime accepts model-produced v4 without downgrade", async () => {
  const fetcher = vi.fn().mockResolvedValue(response(raw("RuntimeV4")));
  vi.stubGlobal("fetch", fetcher);
  expect(await toolClient.runtime()).toEqual(value("RuntimeV4"));
  expect(fetcher).toHaveBeenCalledTimes(1);
  expect(fetcher.mock.calls[0][0]).toBe("/api/v1/chat/tools/runtime");
});
