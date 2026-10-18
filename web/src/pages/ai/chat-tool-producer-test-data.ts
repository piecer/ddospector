import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import type { ChatSession } from "./chat-types";

// Captured ToolLedger bytes, not synthetic hashes computed with the consumer.
// The two review corpora are byte-identical copies of the independent evidence.
export const producerData = resolve("src/pages/ai/chat-tool-producer-data");
function capture<T>(name: string, expected: string): T {
  const bytes = readFileSync(resolve(producerData, name));
  if (createHash("sha256").update(bytes).digest("hex") !== expected)
    throw new Error(`Changed producer capture: ${name}`);
  return JSON.parse(bytes.toString("utf8")) as T;
}
export type GrantVector = {
  label: string;
  session: ChatSession;
  input: { request_id: string; turn_request_id: string; text: string };
  wire: string;
};
export const producer = capture<{
  rows: { label: string; kind: string; wire: string }[];
  grants: GrantVector[];
}>(
  "producer.json",
  "f6d451a242f3e09139314e565a834575ec4061b4098c6565f99917da6820ead5",
);
export const extraProducer = capture<{
  differential: { label: string; value: unknown; producer_accepts: boolean }[];
}>(
  "extra-producer.json",
  "96c5317bb2c86e6f02c12235795c504796d08d879c41e94b6beb2dd5d869bc31",
);
export const grantVectors = capture<{
  grants: (GrantVector & { turn_wire: string })[];
}>(
  "grants.json",
  "d16496f249d49218fc81ef1d581ef1c3bd6bf4c4fd9ecb7303d13fefbd8153f9",
).grants;
export function producerTranscript(label: string) {
  const row = producer.rows.find((r) => r.label === label);
  if (!row || row.kind !== "transcript") throw new Error(label);
  return JSON.parse(row.wire);
}
