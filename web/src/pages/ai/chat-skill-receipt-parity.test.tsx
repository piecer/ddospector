// Synthetic DTO/Response witnesses ONLY: not producer capture or publication proof.
import { afterEach, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { resolve } from "node:path";
import { ToolRecords } from "./ToolRecords";
import { toolClient } from "./chat-tool-client";
import { parseTranscript } from "./chat-tool-wire";
import { decodeJSON, parseTurn } from "./chat-wire";
import { skillTranscript } from "./chat-skill-test-fixtures";
import { turn } from "./chat-test-fixtures";
import type { TranscriptLedger, ToolReadGate } from "./useToolTranscript";

// Canonical Vitest cwd is web; bind the DTO oracle to that checkout, never an editable install.
const root = resolve("..");
const copy = <T,>(value: T): T => JSON.parse(JSON.stringify(value));
const sha = (value: string | Uint8Array) =>
  createHash("sha256").update(value).digest("hex");

function witnesses() {
  const good = copy(skillTranscript);
  // Audit time is independently valid, not tied to a nonexistent Skill timestamp.
  good.calls[0].result.audit.created_at = "2026-10-18T01:00:01Z";
  const bad = copy(good);
  bad.calls[0].result.audit.id = bad.calls[0].result.skill.id;
  return { good, bad };
}

function producer(raw: string) {
  const result = JSON.parse(
    execFileSync(
      resolve(root, ".venv/bin/python"),
      [
        "-c",
        `import hashlib, json, socket, sys
from pathlib import Path
import aiddos.api.chat_tool_models as wire
import aiddos.api.models as domain
import aiddos.api.catalog as catalog
import aiddos.api.validation as validation
from pydantic import ValidationError
root = Path(${JSON.stringify(root)})
origins = {}
for module in (wire, domain, catalog, validation):
    expected = root / 'src' / (module.__name__.replace('.', '/') + '.py')
    assert Path(module.__file__).resolve() == expected.resolve()
    origins[module.__name__] = str(expected)
def deny(*args, **kwargs):
    raise AssertionError('network forbidden in synthetic DTO oracle')
socket.socket.connect = deny
socket.getaddrinfo = deny
raw = sys.stdin.buffer.read()
result = {'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw), 'origins': origins}
try:
    result.update(accepted=True, value=wire.ToolTranscript.model_validate_json(raw).model_dump())
except ValidationError as error:
    result.update(accepted=False, error=str(error))
print(json.dumps(result))`,
      ],
      {
        input: raw,
        encoding: "utf8",
        env: {
          ...process.env,
          PATH: `${root}/.venv/bin:/usr/bin:/bin:/snap/bin`,
          PYTHONPATH: `${root}/src:${root}`,
          PYTHONDONTWRITEBYTECODE: "1",
          UV_OFFLINE: "1",
          UV_NO_SYNC: "1",
        },
      },
    ),
  );
  expect(result.sha256).toBe(sha(raw));
  expect(result.bytes).toBe(new TextEncoder().encode(raw).length);
  expect(result.origins["aiddos.api.chat_tool_models"]).toBe(
    resolve(root, "src/aiddos/api/chat_tool_models.py"),
  );
  return result;
}

function serve(raw: string) {
  const bytes = new TextEncoder().encode(raw);
  const fetch = vi.fn(async (url: string, init: RequestInit) => {
    expect(url).toBe(`/api/v1/chat/turns/${skillTranscript.turn_id}/tools`);
    expect(init.method).toBe("GET");
    const response = new Response(bytes, {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
    // The shipped body reader receives exactly the bytes checked by Python.
    expect(sha(new Uint8Array(await response.clone().arrayBuffer()))).toBe(
      sha(raw),
    );
    return response;
  });
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

afterEach(() => vi.unstubAllGlobals());

it("FE-01 exact synthetic bytes have producer/client parity for the audit.id-only collision", async () => {
  const { good, bad } = witnesses();
  const restored = copy(bad);
  restored.calls[0].result.audit.id = good.calls[0].result.audit.id;
  expect(restored).toEqual(good);
  expect(good.calls[0].result.skill).not.toHaveProperty("created_at");
  expect(good.calls[0].result.audit.created_at).not.toBe(
    good.calls[0].finished_at,
  );
  const valid = JSON.stringify(good),
    invalid = JSON.stringify(bad);
  expect(producer(valid)).toMatchObject({ accepted: true, value: good });
  expect(producer(invalid)).toMatchObject({
    accepted: false,
    error: expect.stringContaining("Invalid Skill creation receipt"),
  });
  const validFetch = serve(valid);
  expect(await toolClient.tools(good.turn_id)).toEqual(good);
  expect(validFetch).toHaveBeenCalledTimes(1);
  expect(
    await parseTranscript(decodeJSON(new TextEncoder().encode(valid))),
  ).toEqual(good);
  const invalidFetch = serve(invalid);
  // Both public decode paths must reject, not sanitize or drop the invalid audit.
  const viaHTTP = toolClient.tools(bad.turn_id);
  const viaParser = parseTranscript(
    decodeJSON(new TextEncoder().encode(invalid)),
  );
  const outcomes = await Promise.allSettled([viaHTTP, viaParser]);
  expect(outcomes.map((outcome) => outcome.status)).toEqual([
    "rejected",
    "rejected",
  ]);
  expect(invalidFetch).toHaveBeenCalledTimes(1);
});

it("FE-01 distinct 64-character non-UUID native Identifiers and exact literals remain accepted", async () => {
  const { good } = witnesses();
  const result = good.calls[0].result;
  result.skill.id = "s".repeat(63) + "1";
  result.audit.entity_id = result.skill.id;
  result.audit.id = "s".repeat(63) + "2";
  const raw = JSON.stringify(good);
  expect(producer(raw)).toMatchObject({ accepted: true, value: good });
  serve(raw);
  expect(await toolClient.tools(good.turn_id)).toEqual(good);
  expect(result.skill.name.en).toBe(" Literal 🌍 ");
  expect(result.skill.description.en).toBe("description\n\t");
  expect(result.skill.instructions.en).toBe(
    "<script>not authority</script>\r\nEND",
  );
});

it.each([false, true])(
  "FE-01 real Response → ToolRecords receipt/navigation boundary (collision=%s)",
  async (collision) => {
    const { good, bad } = witnesses();
    const value = collision ? bad : good;
    const raw = JSON.stringify(value);
    expect(producer(raw).accepted).toBe(!collision);
    const fetch = serve(raw);
    const onViewSkill = vi.fn(),
      onRecord = vi.fn();
    const records: TranscriptLedger = new Map();
    const readGate: ToolReadGate = { owner: null, completed: -Infinity };
    const ui = render(
      <ToolRecords
        turn={parseTurn(turn)}
        locale="en"
        enabled
        viewEpoch={0}
        canWrite={false}
        onViewSkill={onViewSkill}
        onRecord={onRecord}
        records={records}
        readGate={readGate}
      />,
    );
    // Wait for actual reader settlement, not the initial stale/loading UI.
    await waitFor(() => {
      expect(fetch).toHaveBeenCalledTimes(1);
      expect(readGate.owner).toBeNull();
      expect(Number.isFinite(readGate.completed)).toBe(true);
    });
    const saved = `chat-tool-view-saved-${value.calls[0].id}`;
    if (collision) {
      expect(screen.queryByTestId(saved)).not.toBeInTheDocument();
      expect(screen.queryByText(/Saved ·/)).not.toBeInTheDocument();
      expect(screen.getByRole("status")).toHaveTextContent(
        "Tool outcome unknown / stale",
      );
      expect(records.size).toBe(0);
      expect(onRecord).not.toHaveBeenCalled();
      expect(onViewSkill).not.toHaveBeenCalled();
    } else {
      expect(
        screen.getByTestId(`chat-tool-${value.calls[0].id}`),
      ).toHaveTextContent("Saved ·");
      expect(records.get(value.turn_id)).toEqual(value);
      expect(onRecord).toHaveBeenCalledWith(value);
      fireEvent.click(screen.getByTestId(saved));
      expect(onViewSkill).toHaveBeenCalledTimes(1);
      expect(onViewSkill).toHaveBeenCalledWith({
        skill: value.calls[0].result.skill,
        after_revision: value.calls[0].result.after_revision,
      });
    }
    ui.unmount();
  },
);
