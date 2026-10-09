import type { AISettingsInput, AISettingsSnapshot } from "./types";
import { assertSettingsInput, parseSettingsSnapshot } from "./wire";
const MAX_BYTES = 256 * 1024;
async function readJSON(
  response: Response,
  signal: AbortSignal,
): Promise<unknown> {
  const reader = response.body?.getReader();
  if (!reader) throw new Error("Missing AI settings response body.");
  const cancel = () => {
    void reader.cancel().catch(() => undefined);
  };
  signal.addEventListener("abort", cancel, { once: true });
  let complete = false;
  try {
    signal.throwIfAborted();
    const length = response.headers.get("Content-Length");
    if (length !== null && Number(length) > MAX_BYTES)
      throw new Error("AI settings response is too large.");
    const decoder = new TextDecoder("utf-8", { fatal: true });
    let bytes = 0,
      text = "";
    while (true) {
      const chunk = await reader.read();
      signal.throwIfAborted();
      if (chunk.done) break;
      bytes += chunk.value.byteLength;
      if (bytes > MAX_BYTES)
        throw new Error("AI settings response is too large.");
      text += decoder.decode(chunk.value, { stream: true });
    }
    text += decoder.decode();
    complete = true;
    return JSON.parse(text) as unknown;
  } finally {
    signal.removeEventListener("abort", cancel);
    if (!complete) cancel();
    reader.releaseLock();
  }
}
export const AI_SETTINGS_TIMEOUT_MS = 10_000;
async function request(
  method: "GET" | "PUT",
  input?: AISettingsInput,
  signal?: AbortSignal,
): Promise<AISettingsSnapshot> {
  signal?.throwIfAborted();
  if (input !== undefined) assertSettingsInput(input);
  const body = input === undefined ? undefined : JSON.stringify(input);
  if (body && new TextEncoder().encode(body).length > MAX_BYTES)
    throw new Error("AI settings replacement is too large.");
  const controller = new AbortController();
  const cancel = () => controller.abort(signal?.reason);
  signal?.addEventListener("abort", cancel, { once: true });
  let rejectAbort!: (reason: unknown) => void;
  const aborted = new Promise<never>((_, reject) => {
    rejectAbort = reject;
  });
  const onAbort = () => rejectAbort(controller.signal.reason);
  controller.signal.addEventListener("abort", onAbort, { once: true });
  const timer = setTimeout(
    () =>
      controller.abort(
        new DOMException("AI settings request timed out.", "TimeoutError"),
      ),
    AI_SETTINGS_TIMEOUT_MS,
  );
  async function perform() {
    const response = await fetch("/api/v1/ai-settings", {
      method,
      cache: "no-store",
      redirect: "error",
      credentials: "same-origin",
      signal: controller.signal,
      headers: {
        Accept: "application/json",
        ...(input ? { "Content-Type": "application/json" } : {}),
      },
      ...(body === undefined ? {} : { body }),
    });
    if (controller.signal.aborted) {
      void response.body?.cancel().catch(() => undefined);
      controller.signal.throwIfAborted();
    }
    if (response.status !== 200) {
      void response.body?.cancel().catch(() => undefined);
      throw new Error("AI settings request was not acknowledged.");
    }
    const result = parseSettingsSnapshot(
      await readJSON(response, controller.signal),
    );
    if (input && result.revision !== input.revision + 1)
      throw new Error("Contradictory AI settings acknowledgement.");
    controller.signal.throwIfAborted();
    return result;
  }
  try {
    // Bound acknowledgement even when a transport fails to settle on abort.
    return await Promise.race([perform(), aborted]);
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", cancel);
    controller.signal.removeEventListener("abort", onAbort);
  }
}
export const aiSettingsAPI = {
  read: (signal?: AbortSignal) => request("GET", undefined, signal),
  save: (input: AISettingsInput, signal?: AbortSignal) =>
    request("PUT", input, signal),
};
