import { execFileSync } from "node:child_process";
import { resolve } from "node:path";
import { expect, it } from "vitest";
import { parseTranscript } from "./chat-tool-wire";
import type { ToolTranscript } from "./chat-tool-types";
import {
  extraProducer,
  producerData,
  producerTranscript,
} from "./chat-tool-producer-test-data";

// All mutations below are explicit malformed/valid controls derived from actual
// records. They are not alleged ToolLedger output. Revalidate with real Pydantic.
const controls: {
  label: string;
  value: ToolTranscript;
  producer_accepts: boolean;
}[] = [];
for (const label of [
  "saved-requested",
  "saved-awaiting",
  "saved-final",
  "deny-final",
]) {
  controls.push({
    label: `unmodified-${label}`,
    value: producerTranscript(label),
    producer_accepts: true,
  });
}
for (const label of ["saved-final", "deny-final"]) {
  for (const ordering of ["before", "equal", "after"] as const) {
    const value: ToolTranscript = producerTranscript(label);
    const call = value.calls[0];
    // Microsecond controls also ensure no millisecond Date.parse truncation.
    call.decision!.accepted_at = "2026-01-01T00:00:00.000002+00:00";
    call.finished_at = {
      before: "2026-01-01T00:00:00.000001Z",
      equal: "2026-01-01T00:00:00.000002Z",
      after: "2026-01-01T00:00:00.000003Z",
    }[ordering];
    controls.push({
      label: `${label}-finished-${ordering}-decision`,
      value,
      producer_accepts: ordering !== "before",
    });
  }
}
const rows = [...extraProducer.differential, ...controls];
const oracle = JSON.parse(
  execFileSync(
    resolve("../.venv/bin/python"),
    [
      resolve(producerData, "wire-oracle.py"),
      resolve(process.env.CHAT02A_PRODUCER_SOURCE ?? "../src"),
    ],
    {
      input: JSON.stringify(rows),
      encoding: "utf8",
      env: { ...process.env, PYTHONDONTWRITEBYTECODE: "1" },
    },
  ),
) as { label: string; accepted: boolean }[];

for (const [index, row] of rows.entries()) {
  it(`closed-wire/Pydantic parity: ${row.label}`, async () => {
    expect(oracle[index]).toEqual({
      label: row.label,
      accepted: row.producer_accepts,
    });
    if (row.producer_accepts)
      await expect(parseTranscript(row.value)).resolves.toEqual(row.value);
    else await expect(parseTranscript(row.value)).rejects.toThrow();
  });
}
