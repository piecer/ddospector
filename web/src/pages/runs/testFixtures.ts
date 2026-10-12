import { digest } from "../scenarios/json";
import { rows, body } from "./testCorpus";
import { rawJSON } from "./raw";
import { parseDetail } from "./wire";
import { checkpoint } from "./checkpoint";
export async function receiptFixture() {
  const d = await parseDetail(
    rawJSON(body(rows.find((r) => r.state === "QUEUED")!), 32768),
  );
  const { request_id, mode, scenario_id, scenario_version, scenario_digest } =
    d.run;
  const request = {
    request_id,
    mode,
    scenario_id,
    scenario_version,
    scenario_digest,
  };
  return {
    d,
    r: {
      schema_version: 1 as const,
      request,
      request_digest: await digest(request),
      checkpoint: checkpoint(d),
    },
  };
}
