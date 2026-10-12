import type { Detail, Request, RunPage, EventPage } from "./types";
import { bodyLimit, decodeResponse, type Context } from "./client";
import { uuid, requireValue } from "./wire";
import { integer } from "../scenarios/validation";
import { canonical } from "../scenarios/json";
import { parseRequest } from "./receipt";
import { RunError } from "./errors";
export const REQUEST_TIMEOUT = 10_000;
async function request(
  path: string,
  context: Omit<Context, "status">,
  body?: string,
  signal?: AbortSignal,
) {
  signal?.throwIfAborted();
  const controller = new AbortController(),
    started = performance.now();
  const abort = () => controller.abort(signal?.reason);
  signal?.addEventListener("abort", abort, { once: true });
  let rejectAbort!: (reason: unknown) => void;
  const aborted = new Promise<never>((_, reject) => {
    rejectAbort = reject;
  });
  const onAbort = () => rejectAbort(new RunError("RUN_CLIENT_TIMEOUT"));
  controller.signal.addEventListener("abort", onAbort, { once: true });
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT);
  const check = () => {
    if (performance.now() - started >= REQUEST_TIMEOUT) controller.abort();
    controller.signal.throwIfAborted();
  };
  async function perform() {
    const response = await fetch("/api/v1/offline-runs" + path, {
      method: context.method,
      credentials: "same-origin",
      redirect: "error",
      cache: "no-store",
      signal: controller.signal,
      headers: {
        Accept: "application/json",
        ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
      },
      ...(body !== undefined ? { body } : {}),
    });
    if (controller.signal.aborted) {
      void response.body?.cancel().catch(() => undefined);
      check();
    }
    requireValue(!response.redirected);
    const c = { ...context, status: response.status },
      max = bodyLimit(c),
      length = response.headers.get("Content-Length");
    const reader = response.body?.getReader();
    requireValue(reader);
    const cancel = () => {
      void reader.cancel().catch(() => undefined);
    };
    controller.signal.addEventListener("abort", cancel, { once: true });
    let complete = false;
    try {
      requireValue(
        length === null || (/^[0-9]+$/.test(length) && Number(length) <= max),
      );
      let size = 0;
      const chunks: Uint8Array[] = [];
      while (true) {
        const chunk = await reader.read();
        check();
        if (chunk.done) break;
        size += chunk.value.byteLength;
        requireValue(size <= max);
        if (chunk.value.byteLength) chunks.push(chunk.value);
      }
      const bytes = new Uint8Array(size);
      let at = 0;
      for (const part of chunks) {
        bytes.set(part, at);
        at += part.byteLength;
      }
      const parsed = await decodeResponse(bytes, c);
      check();
      complete = true;
      return parsed;
    } finally {
      controller.signal.removeEventListener("abort", cancel);
      if (!complete) cancel();
      reader.releaseLock();
    }
  }
  try {
    return await Promise.race([perform(), aborted]);
  } catch (error) {
    if (error instanceof RunError) throw error;
    throw new RunError(
      controller.signal.aborted ? "RUN_CLIENT_TIMEOUT" : "RUN_CLIENT_INVALID",
    );
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", abort);
    controller.signal.removeEventListener("abort", onAbort);
  }
}
export const runAPI = {
  async get(id: string, signal?: AbortSignal): Promise<Detail> {
    requireValue(uuid(id));
    return (await request(
      "/" + id,
      { method: "GET", kind: "detail", id },
      undefined,
      signal,
    )) as Detail;
  },
  async byRequest(id: string): Promise<Detail> {
    requireValue(uuid(id));
    return (await request("/by-request/" + id, {
      method: "GET",
      kind: "request",
      id,
    })) as Detail;
  },
  async create(input: Request): Promise<Detail> {
    const captured = parseRequest(input);
    return (await request(
      "",
      { method: "POST", kind: "create" },
      canonical(captured),
    )) as Detail;
  },
  async cancel(id: string): Promise<Detail> {
    requireValue(uuid(id));
    return (await request(
      "/" + id + "/cancel",
      { method: "POST", kind: "cancel", id },
      "{}",
    )) as Detail;
  },
  async list(
    after = 0,
    limit = 20,
    through?: number,
    signal?: AbortSignal,
  ): Promise<RunPage> {
    requireValue(
      integer(after, 0, 128) &&
        integer(limit, 1, 20) &&
        (through === undefined || integer(through, 0, 128)),
    );
    return (await request(
      `?after=${after}&limit=${limit}${through === undefined ? "" : `&through=${through}`}`,
      { method: "GET", kind: "list", after, limit, through },
      undefined,
      signal,
    )) as RunPage;
  },
  async events(
    id: string,
    after = 0,
    limit = 16,
    signal?: AbortSignal,
  ): Promise<EventPage> {
    requireValue(uuid(id) && integer(after, 0, 16) && integer(limit, 1, 16));
    return (await request(
      `/${id}/events?after=${after}&limit=${limit}`,
      { method: "GET", kind: "events", id, after, limit },
      undefined,
      signal,
    )) as EventPage;
  },
};
