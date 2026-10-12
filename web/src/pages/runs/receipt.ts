import type { Receipt, Request, Checkpoint } from "./types";
import { rawJSON } from "./raw";
import { canonical, digest } from "../scenarios/json";
import { exact, integer, sha256 } from "../scenarios/validation";
import { requireValue, uuid, parseSummary } from "./wire";
import { freeze, snapshot } from "./object";
export const RECEIPT_KEY = "aiddos.s02.pending.v1";
export function parseRequest(value: unknown): Request {
  value = snapshot(value, 1024);
  requireValue(
    exact(value, [
      "request_id",
      "mode",
      "scenario_id",
      "scenario_version",
      "scenario_digest",
    ]) &&
      uuid(value.request_id) &&
      uuid(value.scenario_id) &&
      value.mode === "OFFLINE" &&
      integer(value.scenario_version, 1, 10) &&
      sha256(value.scenario_digest),
  );
  return freeze(value as Request);
}
export function parseCheckpoint(value: unknown, request: Request): Checkpoint {
  requireValue(exact(value, ["run", "source_revision", "result_digest"]));
  const run = parseSummary(value.run);
  requireValue(
    integer(value.source_revision, request.scenario_version, 1000) &&
      (run.state === "SUCCEEDED"
        ? sha256(value.result_digest)
        : value.result_digest === null),
  );
  requireValue(
    run.request_id === request.request_id &&
      run.mode === request.mode &&
      run.scenario_id === request.scenario_id &&
      run.scenario_version === request.scenario_version &&
      run.scenario_digest === request.scenario_digest,
  );
  return value as Checkpoint;
}
export async function parseReceipt(text: string): Promise<Receipt> {
  requireValue(text.length <= 2048);
  const v = rawJSON(new TextEncoder().encode(text), 2048);
  requireValue(
    exact(v, ["schema_version", "request", "request_digest", "checkpoint"]) &&
      v.schema_version === 1 &&
      sha256(v.request_digest) &&
      canonical(v) === text,
  );
  const request = parseRequest(v.request);
  requireValue((await digest(request)) === v.request_digest);
  if (v.checkpoint !== null) parseCheckpoint(v.checkpoint, request);
  return freeze(v as Receipt);
}
