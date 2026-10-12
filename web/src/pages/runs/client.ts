import { rawJSON } from "./raw";
import { parseDetail, requireValue } from "./wire";
import { parseList, parseEvents } from "./pages";
import { exact } from "../scenarios/validation";
import { errors, RunError } from "./errors";
import { terminal } from "./grammar";
export type Context = {
  method: "GET" | "POST";
  kind: "detail" | "create" | "cancel" | "request" | "list" | "events";
  status: number;
  id?: string;
  after?: number;
  limit?: number;
  through?: number;
};
export const bodyLimit = (c: Context) =>
  c.status >= 300
    ? 1024
    : c.kind === "list"
      ? 131072
      : c.kind === "events"
        ? 16384
        : 32768;
export async function decodeResponse(bytes: Uint8Array, c: Context) {
  const value = rawJSON(bytes, bodyLimit(c));
  if (c.status >= 300) {
    requireValue(
      exact(value, ["code", "message"]) &&
        typeof value.code === "string" &&
        Object.hasOwn(errors, value.code),
    );
    const [status, message] = errors[value.code];
    requireValue(c.status === status && value.message === message);
    throw new RunError(value.code);
  }
  requireValue(
    c.method === (c.kind === "create" || c.kind === "cancel" ? "POST" : "GET"),
  );
  if (c.kind === "list") {
    requireValue(c.status === 200);
    return parseList(value, c.after, c.limit, c.through);
  }
  if (c.kind === "events") {
    requireValue(c.status === 200);
    return parseEvents(value, c.id!, c.after, c.limit);
  }
  const detail = await parseDetail(value);
  if (c.kind === "create")
    requireValue(
      c.status === 200 ||
        (c.status === 202 &&
          detail.run.state === "QUEUED" &&
          detail.run.event_count === 1),
    );
  else if (c.kind === "cancel")
    requireValue(
      c.status === (detail.run.state === "CANCEL_REQUESTED" ? 202 : 200) &&
        (detail.run.state === "CANCEL_REQUESTED" || terminal(detail.run.state)),
    );
  else requireValue(c.status === 200);
  if (c.kind === "request") requireValue(detail.run.request_id === c.id);
  else if (c.kind !== "create") requireValue(detail.run.id === c.id);
  return detail;
}
