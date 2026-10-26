import { execFileSync } from "node:child_process";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { digest } from "../scenarios/json";
import { parseVersion } from "../scenarios/wire";

const candidate = resolve(import.meta.dirname, "../../../..");
function produced(): {
  origin: string;
  module: string;
  bodies: Record<string, string>;
  variants: {
    label: string;
    name: import("./chat-scenario-types").ContractName;
    raw: string;
  }[];
  negatives: {
    name: import("./chat-scenario-types").ContractName;
    path: string[];
    raw: string;
  }[];
} {
  return JSON.parse(
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
}
async function codec() {
  const files = import.meta.glob("./chat-scenario-wire.ts");
  expect(
    Object.keys(files),
    "Missing Identifier-compatible B3 codec",
  ).toHaveLength(1);
  return (await files[
    "./chat-scenario-wire.ts"
  ]()) as typeof import("./chat-scenario-wire");
}

describe("B3 standalone producer-byte parity (not native HTTP)", () => {
  it("accepts model-produced append/read/terminal/empty and version-source variants", async () => {
    const m = await codec();
    for (const entry of produced().variants) {
      expect(await m.parseV4JSON(entry.name, entry.raw), entry.label).toEqual(
        JSON.parse(entry.raw),
      );
    }
  });
  it("captures the whole validated record before asynchronous digest work", async () => {
    const m = await codec();
    const input = JSON.parse(produced().bodies.ScenarioVersion),
      expected = structuredClone(input);
    const pending = m.parseScenarioVersionV4(input);
    input.definition.name = "mutation after entry";
    expect(await pending).toEqual(expected);
  });
  it("enforces raw history/page byte caps and accepts offset beyond total", async () => {
    const m = await codec();
    const raw = produced().bodies.ScenarioHistoryV4;
    const exact =
      raw + " ".repeat(262144 - new TextEncoder().encode(raw).length);
    expect(await m.parseV4JSON("ScenarioHistoryV4", exact)).toEqual(
      JSON.parse(raw),
    );
    await expect(
      m.parseV4JSON("ScenarioHistoryV4", exact + " "),
    ).rejects.toThrow();
    const empty = {
      revision: 0,
      total: 0,
      offset: 100,
      limit: 100,
      items: [],
      execution_enabled: false,
    };
    expect(await m.parseScenarioPageV4(empty, 100, 100)).toEqual(empty);
  });
  it("rejects BOM bytes rather than silently stripping their provenance", async () => {
    const m = await codec();
    await expect(
      m.parseV4JSON(
        "ContextArgs",
        new Uint8Array([
          239,
          187,
          191,
          ...new TextEncoder().encode('{"kind":"scenario_context"}'),
        ]),
      ),
    ).rejects.toThrow();
  });
  it("rejects accessor, foreign-prototype, sparse and extra-property direct inputs without invoking getters", async () => {
    const m = await codec();
    let invoked = false;
    const value = Object.defineProperty({}, "kind", {
      enumerable: true,
      get() {
        invoked = true;
        return "scenario_context";
      },
    });
    await expect(m.parseV4("ContextArgs", value)).rejects.toThrow();
    expect(invoked).toBe(false);
    await expect(
      m.parseV4("ContextArgs", Object.create({ kind: "scenario_context" })),
    ).rejects.toThrow();
    await expect(
      m.parseV4("ContextArgs", { kind: "scenario_context", extra: null }),
    ).rejects.toThrow();
    const fixture = JSON.parse(produced().bodies.ScenarioHistoryV4);
    fixture.versions = new Array(2);
    await expect(
      m.parseScenarioHistoryV4(fixture, "legacy-scenario"),
    ).rejects.toThrow();
  });
  it("separates live captured authority from cold historical consistency", async () => {
    const m = await codec();
    expect(m.boundGrant, "Missing live commitment binding").toBeTypeOf(
      "function",
    );
    const bodies = produced().bodies;
    const g = JSON.parse(bodies.GrantV4),
      request = JSON.parse(bodies.GrantInputV4);
    const commitment = {
      requestedAuthority: "scenario_write_v4" as const,
      request,
      settings_revision: g.settings_revision,
      profile_id: g.profile_id,
      resolved_inputs: g.resolved_inputs,
    };
    expect(await m.boundGrant(g, commitment)).toEqual(g);
    await expect(
      m.boundGrant(g, {
        ...commitment,
        request: { ...request, text: "different" },
      }),
    ).rejects.toThrow();
    const t = JSON.parse(bodies.TranscriptV4);
    expect(await m.parseTranscriptV4(t, t.turn_id)).toEqual(t);
    await expect(m.parseTranscriptV4(t, g.id)).rejects.toThrow();
    expect(await m.boundCall(t.calls[0], g, "2026-01-01T00:02:00Z")).toEqual(
      t.calls[0],
    );
    const c = structuredClone(t.calls[0]);
    c.proposal.input_source = {
      source: "scenario_version",
      reference: { id: "old", version: 1, digest: "a".repeat(64) },
    };
    c.proposal.inputs_digest = await m.inputsDigest(
      c.proposal.input_source,
      m.protectedProjection(c.proposal.after),
    );
    c.proposal.digest = await m.proposalDigest(c.id, c.grant_id, c.proposal);
    c.decision.proposal_digest = c.proposal.digest;
    expect(await m.parseV4("CallV4", c)).toEqual(c); // self-consistency, NOT independent authority
    await expect(m.boundCall(c, g, "2026-01-01T00:02:00Z")).rejects.toThrow();
    c.status = "uncertain";
    c.result = null;
    c.error_code = "CHAT_TOOL_UNCERTAIN";
    const history = await m.parseTranscriptV4({ ...t, calls: [c] }, t.turn_id);
    expect(history.calls[0].result).toBeNull();
    expect(history.calls[0].status).toBe("uncertain");
    const read = {
      ...c,
      tool: "configuration_read",
      arguments: { kind: "scenario_context" },
      proposal: null,
      decision: null,
      status: "requested",
      error_code: null,
      finished_at: null,
    };
    read.args_digest = await digest(read.arguments);
    expect(await m.boundCall(read, g, "2026-01-01T00:02:00Z")).toEqual(read);
  });
  it("rejects the same producer-derived semantic negatives as Python", async () => {
    const m = await codec();
    const fixtures = produced();
    expect(fixtures.negatives.length).toBeGreaterThan(40);
    for (const entry of fixtures.negatives) {
      await expect(
        m.parseV4JSON(entry.name, entry.raw),
        `${entry.name}: ${entry.path}`,
      ).rejects.toThrow();
    }
  });
  it("roundtrips all 53 genuine Python contract shapes through raw v4 ingress", async () => {
    const m = await codec();
    expect(m.parseV4JSON, "Missing closed v4 shape dispatch").toBeTypeOf(
      "function",
    );
    const fixtures = produced().bodies;
    expect(Object.keys(fixtures)).toHaveLength(53);
    for (const [name, raw] of Object.entries(fixtures)) {
      expect(
        await m.parseV4JSON(
          name as import("./chat-scenario-types").ContractName,
          raw,
        ),
        name,
      ).toEqual(JSON.parse(raw));
    }
    const raw = fixtures.GrantV4;
    for (const bad of [
      raw.replace('"schema_version":4', '"schema_version":4e0'),
      raw.replace('"schema_version":4', '"schema_version":4.0'),
      raw.replace(
        '"schema_version":4',
        '"schema_version":4,"schema_version":4',
      ),
      raw.replace(
        '"schema_version":4',
        '"schema_version":4,"schema_\\u0076ersion":4',
      ),
      raw.replace('"profile_id":"local"', '"profile_id":"\\ud800"'),
      raw + " ".repeat(32768),
    ]) {
      await expect(m.parseV4JSON("GrantV4", bad)).rejects.toThrow();
    }
    await expect(
      m.parseV4JSON("GrantV4", new Uint8Array([255])),
    ).rejects.toThrow();
  });
  it("validates every history/page member, literal selector and exact count equations", async () => {
    const m = await codec();
    expect(m.parseScenarioHistoryV4, "Missing full history codec").toBeTypeOf(
      "function",
    );
    const fixtures = produced().bodies;
    const history = JSON.parse(fixtures.ScenarioHistoryV4),
      page = JSON.parse(fixtures.ScenarioPageV4);
    expect(await m.parseScenarioHistoryV4(history, "legacy-scenario")).toEqual(
      history,
    );
    expect(await m.parseScenarioPageV4(page, 0, 50)).toEqual(page);
    await expect(
      m.parseScenarioHistoryV4(history, "foreign"),
    ).rejects.toThrow();
    await expect(m.parseScenarioPageV4(page, 0, 49)).rejects.toThrow();
    await expect(
      m.parseScenarioPageV4({ ...page, revision: 1 }, 0, 50),
    ).rejects.toThrow();
    history.versions[0].definition.name = "unselected corrupted";
    await expect(
      m.parseScenarioHistoryV4(history, "legacy-scenario"),
    ).rejects.toThrow();
    page.items[0].target_snapshot.address = "https://foreign";
    await expect(m.parseScenarioPageV4(page, 0, 50)).rejects.toThrow();
  });
  it("accepts full Python-produced historical Identifier records without changing manual UUID rules", async () => {
    const m = await codec();
    const fixture = produced();
    expect(fixture.origin).toContain("not native HTTP capture");
    expect(fixture.module).toBe(
      resolve(candidate, "src/aiddos/api/chat_scenario_models.py"),
    );
    const record = JSON.parse(fixture.bodies.ScenarioVersion);
    expect(await m.parseScenarioVersionV4(record)).toEqual(record);
    await expect(parseVersion(record)).rejects.toThrow();
    await expect(
      m.parseScenarioVersionV4({ ...record, digest: "a".repeat(64) }),
    ).rejects.toThrow();
  });
});
