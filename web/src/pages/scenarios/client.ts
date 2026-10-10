import { canonical, parseJSON, utf8Length } from "./json";
import { exact, identifier, integer, validDefinition } from "./validation";
import { invalid, parseHistory, parsePage, parseVersion } from "./wire";
import type { ScenarioHistory, ScenarioReceipt, Submission } from "./types";
const BASE = "/api/v1/scenarios";
export const SCENARIO_TIMEOUT_MS = 10_000;
const fixedErrors: Record<string, number> = {
  SCENARIO_CONFLICT: 409,
  SCENARIO_NOT_FOUND: 404,
  SCENARIO_LIMIT_REACHED: 409,
  SCENARIO_STATE_CORRUPT: 503,
  SCENARIO_STATE_UNAVAILABLE: 503,
  SCENARIO_COMMIT_UNCERTAIN: 503,
  STATE_CORRUPT: 503,
  STATE_UNAVAILABLE: 503,
  INVALID_REFERENCE: 422,
  VALIDATION_ERROR: 422,
};
export class ScenarioError extends Error {
  constructor(public readonly code: string) {
    super("Scenario request failed.");
  }
}
async function readJSON(
  response: Response,
  max: number,
  signal: AbortSignal,
): Promise<unknown> {
  const reader = response.body?.getReader();
  if (!reader) return invalid();
  const cancel = () => {
    void reader.cancel().catch(() => undefined);
  };
  signal.addEventListener("abort", cancel, { once: true });
  let complete = false;
  try {
    signal.throwIfAborted();
    const length = response.headers.get("Content-Length");
    if (length !== null && (!/^[0-9]+$/.test(length) || Number(length) > max))
      return invalid();
    const decoder = new TextDecoder("utf-8", { fatal: true });
    let bytes = 0,
      text = "";
    while (true) {
      const chunk = await reader.read();
      signal.throwIfAborted();
      if (chunk.done) break;
      bytes += chunk.value.byteLength;
      if (bytes > max) return invalid();
      text += decoder.decode(chunk.value, { stream: true });
    }
    text += decoder.decode();
    complete = true;
    return parseJSON(text);
  } finally {
    signal.removeEventListener("abort", cancel);
    if (!complete) cancel();
    reader.releaseLock();
  }
}
async function request<T>(
  path: string,
  method: "GET" | "POST" | "PUT",
  max: number,
  parse: (v: unknown) => Promise<T>,
  body?: string,
  signal?: AbortSignal,
): Promise<T> {
  signal?.throwIfAborted();
  const controller = new AbortController(),
    started = performance.now();
  const cancel = () => controller.abort(signal?.reason);
  signal?.addEventListener("abort", cancel, { once: true });
  let rejectAbort!: (reason: unknown) => void;
  const aborted = new Promise<never>((_, reject) => {
    rejectAbort = reject;
  });
  const onAbort = () => rejectAbort(controller.signal.reason);
  controller.signal.addEventListener("abort", onAbort, { once: true });
  const timeout = () =>
    controller.abort(
      new DOMException("Scenario request timed out.", "TimeoutError"),
    );
  const timer = setTimeout(timeout, SCENARIO_TIMEOUT_MS);
  const check = () => {
    if (performance.now() - started >= SCENARIO_TIMEOUT_MS) timeout();
    controller.signal.throwIfAborted();
  };
  async function perform(): Promise<T> {
    const response = await fetch(BASE + path, {
      method,
      credentials: "same-origin",
      redirect: "error",
      cache: "no-store",
      signal: controller.signal,
      headers: {
        Accept: "application/json",
        ...(body ? { "Content-Type": "application/json" } : {}),
      },
      ...(body ? { body } : {}),
    });
    if (controller.signal.aborted) {
      void response.body?.cancel().catch(() => undefined);
      check();
    }
    const value = await readJSON(response, max, controller.signal);
    check();
    if (
      response.redirected ||
      response.status !== (method === "POST" ? 201 : 200)
    ) {
      if (
        exact(value, ["code", "message"]) &&
        typeof value.code === "string" &&
        typeof value.message === "string" &&
        fixedErrors[value.code] === response.status
      )
        throw new ScenarioError(value.code);
      return invalid();
    }
    const result = await parse(value);
    check();
    return result;
  }
  try {
    return await Promise.race([perform(), aborted]);
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", cancel);
    controller.signal.removeEventListener("abort", onAbort);
  }
}
async function read(offset = 0, limit = 50, signal?: AbortSignal) {
  if (!integer(offset, 0, 100) || !integer(limit, 1, 100)) return invalid();
  return request(
    `?offset=${offset}&limit=${limit}`,
    "GET",
    1048576,
    (v) => parsePage(v, offset, limit),
    undefined,
    signal,
  );
}
async function history(
  id: string,
  signal?: AbortSignal,
): Promise<ScenarioHistory> {
  if (!identifier(id)) return invalid();
  return request(
    "/" + id,
    "GET",
    262144,
    (v) => parseHistory(v, id),
    undefined,
    signal,
  );
}
async function save(
  input: Submission,
  signal?: AbortSignal,
): Promise<ScenarioReceipt> {
  if (
    !exact(input, ["revision", "definition", "opened"]) ||
    !integer(input.revision, 0, Number.MAX_SAFE_INTEGER - 1) ||
    !validDefinition(input.definition) ||
    (input.opened !== null &&
      (!exact(input.opened, ["id", "version"]) ||
        !identifier(input.opened.id) ||
        !integer(input.opened.version, 1, 9)))
  )
    return invalid();
  // Snapshot BEFORE the first await; a changing draft cannot rewrite acknowledgement intent.
  const captured = JSON.parse(canonical(input)) as Submission;
  const body = canonical({
    revision: captured.revision,
    definition: captured.definition,
  });
  if (utf8Length(body) > 8192) return invalid();
  return request(
    captured.opened ? "/" + captured.opened.id : "",
    captured.opened ? "PUT" : "POST",
    262144,
    async (v) => {
      if (
        !exact(v, ["revision", "scenario", "execution_enabled"]) ||
        v.revision !== captured.revision + 1 ||
        !integer(v.revision, 1, 1000) ||
        v.execution_enabled !== false
      )
        return invalid();
      const scenario = await parseVersion(v.scenario);
      if (
        canonical(scenario.definition) !== canonical(captured.definition) ||
        scenario.version !==
          (captured.opened ? captured.opened.version + 1 : 1) ||
        (captured.opened && scenario.id !== captured.opened.id)
      )
        return invalid();
      return v as ScenarioReceipt;
    },
    body,
    signal,
  );
}
async function verify(
  receipt: ScenarioReceipt,
  signal?: AbortSignal,
): Promise<ScenarioHistory> {
  const result = await history(receipt.scenario.id, signal);
  if (
    result.revision < receipt.revision ||
    !result.versions.some((v) => canonical(v) === canonical(receipt.scenario))
  )
    return invalid();
  return result;
}
export const scenarioAPI = { read, history, save, verify };
