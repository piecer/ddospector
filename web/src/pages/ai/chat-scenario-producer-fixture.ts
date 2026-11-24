// Test-only loader for current public ASGI scenario-tool capture bytes.
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

type Scope = "create" | "append" | "reconcile";
type Body = {
  path: string;
  sha256: string;
  size: number;
  status: number;
  media_type: string;
  method: string;
  path_and_query: string;
  request_sha256: string;
  raw_utf8: string;
};
type Bundle = {
  schema_version: 1;
  provenance: string;
  capture_command: string;
  scopes: Record<
    Scope,
    {
      provenance: string;
      source_sha256: Record<string, string>;
      bodies: Record<string, Body>;
    }
  >;
};

const bundleBytes = readFileSync(
  resolve(import.meta.dirname, "chat-scenario-producer-data/current.json"),
);
const bundle = JSON.parse(bundleBytes.toString("utf8")) as Bundle;
const aliases = {
  "append-old-source-saved": ["append", "saved"],
  "append-old-source-turn": ["append", "turn"],
  "create-decision": ["create", "decision"],
  "create-grant": ["create", "grant"],
  "create-proposal": ["create", "proposal"],
  "create-saved": ["create", "saved"],
  "create-sessions": ["create", "sessions"],
  "create-turn": ["create", "turn"],
  "fence-empty": ["create", "fence"],
  "fence-uncertain": ["reconcile", "fence"],
  reconcile: ["reconcile", "reconcile"],
  "reconcile-state": ["reconcile", "state"],
  runtime: ["create", "runtime"],
  "state-empty": ["create", "state-before"],
  "uncertain-transcript": ["reconcile", "uncertain"],
  "uncertain-turn": ["reconcile", "turn"],
} as const satisfies Record<string, readonly [Scope, string]>;

export type ScenarioProducerName = keyof typeof aliases;
export const scenarioProducerBundleSha256 = createHash("sha256")
  .update(bundleBytes)
  .digest("hex");

export function scenarioProducerBytes(name: ScenarioProducerName): string {
  if (bundle.schema_version !== 1) throw new Error("Invalid scenario producer bundle.");
  const [scope, key] = aliases[name];
  const body = bundle.scopes[scope]?.bodies[key];
  if (!body) throw new Error(`Missing scenario producer body: ${scope}/${key}`);
  const bytes = Buffer.from(body.raw_utf8, "utf8");
  if (
    bytes.byteLength !== body.size ||
    createHash("sha256").update(bytes).digest("hex") !== body.sha256 ||
    !body.media_type.startsWith("application/json")
  )
    throw new Error(`Invalid scenario producer body: ${scope}/${key}`);
  return body.raw_utf8;
}

export function scenarioProducerValue(name: ScenarioProducerName) {
  return JSON.parse(scenarioProducerBytes(name));
}
