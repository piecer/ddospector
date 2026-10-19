import { createHash } from "node:crypto";
import { describe, expect, it, vi } from "vitest";
import producer from "../pages/ai/chat-target-producer-data/producer.json";
import {
  observePersistedGrant,
  type GrantObservationInput,
} from "../../e2e/chat-grant-observer";

// Inherited actual GET response bytes, not a fresh browser reproduction.
// Request bodies are reconstructed bindings, NOT captured original requests.
const captured = producer.responses[7];
const session = JSON.parse(producer.responses[1].raw_utf8);
const turn = JSON.parse(producer.responses[8].raw_utf8);
const receipt = JSON.parse(captured.raw_utf8);
function fixture() {
  const post = {
    method: "POST",
    path: "/api/v1/chat/tool-grants",
    status: 201,
    body: {
      schema_version: 2,
      scope: "target_create",
      request_id: receipt.request_id,
      session_id: session.id,
      turn_request_id: turn.request_id,
      expected_sequence: session.sequence,
      text: turn.user_text,
    },
  };
  const observedTurn = {
    method: "POST",
    path: `/api/v1/chat/sessions/${session.id}/tool-turns`,
    body: {
      request_id: turn.request_id,
      expected_sequence: session.sequence,
      text: turn.user_text,
      grant_id: receipt.id,
    },
  };
  const get = vi.fn<GrantObservationInput["get"]>(async () => ({
    status: 200,
    body: captured.raw_utf8,
  }));
  return {
    post,
    session: { ...session },
    prompt: turn.user_text as string,
    authority: "target_create_v2" as const,
    observedTurn,
    get,
    now: () => Date.parse(receipt.created_at) + 1000,
    clock: () => 0,
  };
}

describe("persisted grant observer (offline harness, not Chromium reproduction)", () => {
  it("reads exactly one literal GET without requiring the original response body", async () => {
    expect(createHash("sha256").update(captured.raw_utf8).digest("hex")).toBe(
      "5b12d63bc5a39e8f3a3c4a5ff7f0840864866a02ad98d11d3c8104edc3e63c9e",
    );
    const f = fixture();
    const result = await observePersistedGrant(f);
    expect(f.get).toHaveBeenCalledExactlyOnceWith(captured.path, {
      timeout: 15_000,
      maxRetries: 0,
      maxRedirects: 0,
    });
    expect(result.source).toBe("persisted-grant-by-request-GET");
    expect(result.originalResponseBody).toBe("not-observed");
    expect(result.grant).toEqual(receipt);
    expect(result.rawReadback).toBe(captured.raw_utf8);
  });

  it("passes only the remaining budget after pre-dispatch elapsed work", async () => {
    const f = fixture();
    let clockCalls = 0;
    const result = await observePersistedGrant({
      ...f,
      clock: () => (clockCalls++ === 0 ? 0 : 2),
    });
    expect(f.get).toHaveBeenCalledExactlyOnceWith(captured.path, {
      timeout: 14_998,
      maxRetries: 0,
      maxRedirects: 0,
    });
    expect(result.grant).toEqual(receipt);
    expect(result.rawReadback).toBe(captured.raw_utf8);
  });
});

// SYNTHETIC v3 observer fixture, not an actual producer/browser capture.
function skillFixture(status: "pending" | "consumed" = "pending") {
  const f = fixture();
  const grant = {
    ...receipt,
    schema_version: 3,
    scope: "skill_create",
    status,
    read_scope: ["skills", "skill"],
    proposal_tools: ["skill_create"],
  };
  f.get.mockResolvedValue({ status: 200, body: JSON.stringify(grant) });
  return {
    ...f,
    authority: "skill_create_v3" as const,
    post: {
      ...f.post,
      body: { ...f.post.body, schema_version: 3, scope: "skill_create" },
    },
    skillGrant: grant,
  };
}

describe("Skill v3 one-shot observer, synthetic controls only", () => {
  it.each(["pending", "consumed"] as const)(
    "binds exact %s v3 without rewriting provenance",
    async (status) => {
      const f = skillFixture(status);
      const record = vi.fn();
      if (status === "consumed")
        f.now = () => Date.parse(receipt.expires_at) + 1;
      const result = await observePersistedGrant({ ...f, record });
      expect(result.grant).toEqual(f.skillGrant);
      expect(result.originalResponseBody).toBe("not-observed");
      expect(result.source).toBe("persisted-grant-by-request-GET");
      expect(f.get).toHaveBeenCalledExactlyOnceWith(captured.path, {
        timeout: 15_000,
        maxRetries: 0,
        maxRedirects: 0,
      });
      expect(record.mock.calls.map(([fact]) => fact.stage)).toEqual([
        "original",
        "readback-start",
        "readback-response",
        "validated",
      ]);
    },
  );
  it.each([
    ["schema_version", 2],
    ["scope", "target_create"],
    ["read_scope", ["agent_profile", "skills", "skill"]],
    ["proposal_tools", ["agent_profile_update"]],
    ["proposal_fields", ["name"]],
    ["id", "abcdef01-2345-4678-9abc-def012345678"],
    ["request_id", "abcdef01-2345-4678-9abc-def012345678"],
    ["session_id", "abcdef01-2345-4678-9abc-def012345678"],
    ["turn_request_id", "abcdef01-2345-4678-9abc-def012345678"],
    ["expected_sequence", 1],
    ["settings_revision", 2],
    ["profile_id", "other"],
    ["text_sha256", "0".repeat(64)],
    ["status", "revoked"],
    ["extra", true],
  ])("rejects v3 altered binding %s", async (key, value) => {
    const f = skillFixture();
    f.get.mockResolvedValue({
      status: 200,
      body: JSON.stringify({ ...f.skillGrant, [key as string]: value }),
    });
    await expect(observePersistedGrant(f)).rejects.toThrow();
    expect(f.get).toHaveBeenCalledTimes(1);
  });
  it.each([
    [1, 3],
    [2, 3],
    [3, 1],
    [3, 2],
  ])(
    "rejects closed cross-authority substitution %s → %s",
    async (wanted, supplied) => {
      const f =
        wanted === 1 ? legacy() : wanted === 2 ? fixture() : skillFixture();
      const grant =
        supplied === 1
          ? legacy().legacyGrant
          : supplied === 2
            ? receipt
            : skillFixture().skillGrant;
      f.get.mockResolvedValue({ status: 200, body: JSON.stringify(grant) });
      await expect(observePersistedGrant(f)).rejects.toThrow();
      expect(f.get).toHaveBeenCalledTimes(1);
    },
  );
  it("denies mismatched v3 POST scope before GET", async () => {
    const f = skillFixture();
    f.post.body.scope = "target_create";
    await expect(observePersistedGrant(f)).rejects.toThrow();
    expect(f.get).not.toHaveBeenCalled();
  });
  it("rejects late v3 read without retry or a validated fact", async () => {
    const f = skillFixture();
    let elapsed = 0;
    f.get.mockImplementation(async () => {
      elapsed = 15_001;
      return { status: 200, body: JSON.stringify(f.skillGrant) };
    });
    const record = vi.fn();
    await expect(
      observePersistedGrant({ ...f, record, clock: () => elapsed }),
    ).rejects.toThrow("deadline");
    expect(f.get).toHaveBeenCalledTimes(1);
    expect(record.mock.calls.some(([fact]) => fact.stage === "validated")).toBe(
      false,
    );
  });
});

const other = "abcdef01-2345-4678-9abc-def012345678";
describe("closed identity and authority bindings", () => {
  it.each([
    ["id", other],
    ["request_id", other],
    ["session_id", other],
    ["turn_request_id", other],
    ["expected_sequence", 1],
    ["profile_id", "another-profile"],
    ["settings_revision", 2],
    ["text_sha256", "0".repeat(64)],
    ["schema_version", 1],
    ["schema_version", 3],
    ["scope", "agent_v1"],
    ["read_scope", ["agent_profile", "skills", "skill"]],
    ["proposal_tools", ["agent_profile_update"]],
    ["proposal_fields", ["name", "skill_ids"]],
    ["status", "revoked"],
    ["status", "expired"],
    ["status", "issued"],
    ["expected_sequence", "0"],
    ["expected_sequence", -1],
    ["id", other.toUpperCase()],
    ["request_id", ` ${other}`],
    ["created_at", "not-a-date"],
    ["expires_at", "2026-10-18T12:40:38.845271+00:00"],
    ["expires_at", "2026-10-18T12:39:38.845272+00:00"],
    ["extra", true],
  ])("rejects synthetic readback mutation %s=%j", async (key, value) => {
    const f = fixture();
    f.get.mockResolvedValue({
      status: 200,
      body: JSON.stringify({ ...receipt, [key as string]: value }),
    });
    await expect(observePersistedGrant(f)).rejects.toThrow();
    expect(f.get).toHaveBeenCalledTimes(1);
  });

  it.each(Object.keys(receipt))(
    "rejects a missing required readback field %s",
    async (key) => {
      const f = fixture();
      const malformed = { ...receipt };
      delete malformed[key];
      f.get.mockResolvedValue({ status: 200, body: JSON.stringify(malformed) });
      await expect(observePersistedGrant(f)).rejects.toThrow();
      expect(f.get).toHaveBeenCalledTimes(1);
    },
  );

  type Fixture = ReturnType<typeof fixture>;
  const mutations: [string, (f: Fixture) => void][] = [
    [
      "POST status",
      (f) => {
        f.post.status = 500;
      },
    ],
    [
      "POST reused 200",
      (f) => {
        f.post.status = 200;
      },
    ],
    [
      "POST method",
      (f) => {
        f.post.method = "GET";
      },
    ],
    [
      "POST path",
      (f) => {
        f.post.path += "/elsewhere";
      },
    ],
    [
      "POST request",
      (f) => {
        f.post.body.request_id = other;
      },
    ],
    [
      "POST session",
      (f) => {
        f.post.body.session_id = other;
      },
    ],
    [
      "POST turn",
      (f) => {
        f.post.body.turn_request_id = other;
      },
    ],
    [
      "POST sequence",
      (f) => {
        f.post.body.expected_sequence = 1;
      },
    ],
    [
      "POST text",
      (f) => {
        f.post.body.text += " altered";
      },
    ],
    [
      "POST scope",
      (f) => {
        f.post.body.scope = "agent_v1";
      },
    ],
    [
      "POST schema",
      (f) => {
        f.post.body.schema_version = 1;
      },
    ],
    [
      "session id",
      (f) => {
        f.session.id = other;
      },
    ],
    [
      "session sequence",
      (f) => {
        f.session.sequence = 1;
      },
    ],
    [
      "session profile",
      (f) => {
        f.session.profile_id = "another-profile";
      },
    ],
    [
      "session settings",
      (f) => {
        f.session.settings_revision = 2;
      },
    ],
    [
      "independent prompt",
      (f) => {
        f.prompt += " altered";
      },
    ],
    [
      "turn method",
      (f) => {
        f.observedTurn.method = "GET";
      },
    ],
    [
      "turn session path",
      (f) => {
        f.observedTurn.path = `/api/v1/chat/sessions/${other}/tool-turns`;
      },
    ],
    [
      "turn request",
      (f) => {
        f.observedTurn.body.request_id = other;
      },
    ],
    [
      "turn grant",
      (f) => {
        f.observedTurn.body.grant_id = other;
      },
    ],
    [
      "turn sequence",
      (f) => {
        f.observedTurn.body.expected_sequence = 1;
      },
    ],
    [
      "turn text",
      (f) => {
        f.observedTurn.body.text += " altered";
      },
    ],
  ];
  it.each(mutations)(
    "fails closed on independent %s",
    async (_name, mutate) => {
      const f = fixture();
      mutate(f);
      await expect(observePersistedGrant(f)).rejects.toThrow();
      expect(f.get.mock.calls.length).toBeLessThanOrEqual(1);
    },
  );
  it.each([
    "",
    "NOT-A-UUID",
    other.toUpperCase(),
    `${other} `,
    other.replaceAll("-", ""),
    `${other}/../x`,
  ])(
    "never repairs malformed literal request ID %j or performs its GET",
    async (id) => {
      const f = fixture();
      f.post.body.request_id = id;
      await expect(observePersistedGrant(f)).rejects.toThrow();
      expect(f.get).not.toHaveBeenCalled();
    },
  );
  it("does not let agreeing POST/receipt override original session sequence", async () => {
    const f = fixture();
    f.post.body.expected_sequence = 1;
    f.observedTurn.body.expected_sequence = 1;
    f.get.mockResolvedValue({
      status: 200,
      body: JSON.stringify({ ...receipt, expected_sequence: 1 }),
    });
    await expect(observePersistedGrant(f)).rejects.toThrow();
  });
  it("rejects actual v2 as Agent authority", async () => {
    await expect(
      observePersistedGrant({ ...fixture(), authority: "agent_v1" }),
    ).rejects.toThrow();
  });
});

// Synthetic valid legacy authority, never described as actual v1 capture.
function legacy() {
  const f = fixture();
  const body = {
    request_id: receipt.request_id,
    session_id: session.id,
    turn_request_id: turn.request_id,
    expected_sequence: session.sequence,
    text: turn.user_text,
  };
  const grant = {
    ...receipt,
    schema_version: 1,
    read_scope: ["agent_profile", "skills", "skill"],
    proposal_fields: ["name", "skill_ids"],
  };
  delete grant.scope;
  delete grant.proposal_tools;
  f.get.mockResolvedValue({ status: 200, body: JSON.stringify(grant) });
  return {
    ...f,
    post: { ...f.post, body },
    authority: "agent_v1" as const,
    legacyGrant: grant,
  };
}
describe("legacy and lifecycle truth", () => {
  it("accepts synthetic valid v1 pending with exact legacy scope", async () => {
    const f = legacy();
    const result = await observePersistedGrant(f);
    expect(result.grant).toMatchObject({
      schema_version: 1,
      status: "pending",
      proposal_fields: ["name", "skill_ids"],
    });
    expect(f.get).toHaveBeenCalledTimes(1);
  });
  it("rejects valid legacy receipt under Target authority", async () => {
    await expect(
      observePersistedGrant({ ...legacy(), authority: "target_create_v2" }),
    ).rejects.toThrow();
  });
  it("rejects a valid v1 receipt substituted behind a valid Target POST", async () => {
    const f = fixture();
    f.get.mockResolvedValue({
      status: 200,
      body: JSON.stringify(legacy().legacyGrant),
    });
    await expect(observePersistedGrant(f)).rejects.toThrow();
    expect(f.get).toHaveBeenCalledTimes(1);
  });
  it("rejects actual v2 readback substituted behind a valid Agent POST", async () => {
    const f = legacy();
    f.get.mockResolvedValue({ status: 200, body: captured.raw_utf8 });
    await expect(observePersistedGrant(f)).rejects.toThrow();
    expect(f.get).toHaveBeenCalledTimes(1);
  });
  it("rejects explicit v1 request schema even with valid v1 response", async () => {
    const f = legacy();
    await expect(
      observePersistedGrant({
        ...f,
        post: { ...f.post, body: { ...f.post.body, schema_version: 1 } },
      }),
    ).rejects.toThrow();
  });
  it.each(["read_scope", "proposal_fields"])(
    "rejects corrupted v1 %s",
    async (key) => {
      const f = legacy();
      f.get.mockResolvedValue({
        status: 200,
        body: JSON.stringify({ ...f.legacyGrant, [key]: [] }),
      });
      await expect(observePersistedGrant(f)).rejects.toThrow();
    },
  );
  it.each([1, 2])(
    "retains consumed status for v%s rather than inventing pending/issued",
    async (version) => {
      const f = legacy();
      const input = version === 1 ? f : fixture();
      input.get.mockResolvedValue({
        status: 200,
        body: JSON.stringify({
          ...(version === 1 ? f.legacyGrant : receipt),
          status: "consumed",
        }),
      });
      const result = await observePersistedGrant(input);
      expect(result.grant.status).toBe("consumed");
      expect(result.originalResponseBody).toBe("not-observed");
      expect(input.get).toHaveBeenCalledTimes(1);
    },
  );
});

describe("bounded observation and evidence", () => {
  it("keeps the producer's sub-millisecond expiry precision", async () => {
    const f = fixture();
    // Captured expiry ends .845271; .845000 is still before that instant.
    f.now = () => Date.parse(receipt.expires_at);
    expect((await observePersistedGrant(f)).grant.status).toBe("pending");
  });
  it("rejects a pending receipt past its actual expiry", async () => {
    const f = fixture();
    f.now = () => Date.parse(receipt.expires_at) + 1;
    await expect(observePersistedGrant(f)).rejects.toThrow();
    expect(f.get).toHaveBeenCalledTimes(1);
  });
  it("accepts consumed history after expiry without rewriting its state", async () => {
    const f = fixture();
    f.now = () => Date.parse(receipt.expires_at) + 1;
    f.get.mockResolvedValue({
      status: 200,
      body: JSON.stringify({ ...receipt, status: "consumed" }),
    });
    expect((await observePersistedGrant(f)).grant.status).toBe("consumed");
  });
  it("rejects GET completion beyond the same bounded deadline", async () => {
    const f = fixture();
    let elapsed = 0;
    f.get.mockImplementation(async () => {
      elapsed = 15_001;
      return { status: 200, body: captured.raw_utf8 };
    });
    await expect(
      observePersistedGrant({ ...f, clock: () => elapsed }),
    ).rejects.toThrow("deadline");
    expect(f.get).toHaveBeenCalledTimes(1);
  });
  it("bounds a never-settling read and clears its timer without retry", async () => {
    vi.useFakeTimers();
    try {
      const f = fixture();
      f.get.mockImplementation(() => new Promise(() => {}));
      const assertion = expect(observePersistedGrant(f)).rejects.toThrow(
        "deadline",
      );
      await vi.advanceTimersByTimeAsync(15_000);
      await assertion;
      expect(f.get).toHaveBeenCalledTimes(1);
      expect(vi.getTimerCount()).toBe(0);
    } finally {
      vi.useRealTimers();
    }
  });
  it("records source-labeled GET evidence even when its receipt is invalid", async () => {
    const f = fixture();
    f.get.mockResolvedValue({ status: 404, body: '{"code":"CHAT_NOT_FOUND"}' });
    const record = vi.fn();
    await expect(observePersistedGrant({ ...f, record })).rejects.toThrow();
    expect(record.mock.calls.map(([fact]) => fact.stage)).toEqual([
      "original",
      "readback-start",
      "readback-response",
    ]);
    expect(record.mock.calls[0][0]).toMatchObject({
      source: "observed-browser-POST",
      originalResponseBody: "not-observed",
      post: f.post,
      session: f.session,
      observedTurn: f.observedTurn,
    });
    expect(record.mock.calls[2][0]).toMatchObject({
      source: "persisted-grant-by-request-GET",
      path: captured.path,
      status: 404,
      body: '{"code":"CHAT_NOT_FOUND"}',
    });
  });
  it("never reads even an unavailable historical response body", async () => {
    const f = fixture();
    const bodyRead = vi.fn(() => {
      throw new Error("historical CDP body unavailable (synthetic control)");
    });
    Object.defineProperty(f.post, "json", { get: bodyRead });
    const record = vi.fn();
    await observePersistedGrant({ ...f, record });
    expect(bodyRead).not.toHaveBeenCalled();
    expect(f.get).toHaveBeenCalledTimes(1);
    expect(record.mock.calls.at(-1)?.[0]).toMatchObject({
      stage: "validated",
      source: "persisted-grant-by-request-GET",
      status: "pending",
    });
  });
});

describe("one-shot readback failure boundaries", () => {
  it.each([404, 429, 500, 201, 302])(
    "rejects GET HTTP %s without retry",
    async (status) => {
      const f = fixture();
      f.get.mockResolvedValue({ status, body: captured.raw_utf8 });
      await expect(observePersistedGrant(f)).rejects.toThrow();
      expect(f.get).toHaveBeenCalledTimes(1);
    },
  );
  it("propagates the exact transport failure without retry", async () => {
    const f = fixture();
    const failure = new Error("readback disconnected");
    f.get.mockRejectedValue(failure);
    await expect(observePersistedGrant(f)).rejects.toBe(failure);
    expect(f.get).toHaveBeenCalledTimes(1);
  });
  it.each([
    "",
    "null",
    "[]",
    "{}",
    "{malformed",
    "{}".repeat(8193),
    captured.raw_utf8.replace(
      '"expected_sequence":0',
      '"expected_sequence":0.0',
    ),
    captured.raw_utf8.replace(
      '"expected_sequence":0',
      '"expected_sequence":0e0',
    ),
    captured.raw_utf8.replace(
      '"status":"pending"',
      '"status":"revoked","status":"pending"',
    ),
    captured.raw_utf8.replace(
      '"status":"pending"',
      '"st\\u0061tus":"pending","status":"pending"',
    ),
  ])("rejects missing/malformed/schema/lexical readback %#", async (body) => {
    const f = fixture();
    f.get.mockResolvedValue({ status: 200, body });
    await expect(observePersistedGrant(f)).rejects.toThrow();
    expect(f.get).toHaveBeenCalledTimes(1);
  });
});
