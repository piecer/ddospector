import { chatCodes } from "./chat-types";
import type {
  ChatCode,
  ChatRuntime,
  ChatSession,
  ChatTurn,
} from "./chat-types";
import {
  ChatEvents,
  decodeJSON,
  FRAME_LIMIT,
  invalid,
  JSON_LIMIT,
  parseHistory,
  parseRuntime,
  parseSession,
  parseSessions,
  parseTurn,
  reconcileTurn,
  terminal,
  uuid,
  validText,
} from "./chat-wire";
import { parseJSON, utf8Length } from "../scenarios/json";
export class ChatRequestError extends Error {
  constructor(
    readonly code: ChatCode,
    readonly definite: boolean,
  ) {
    super(code);
  }
}
const base = "/api/v1/chat";
/** Timers and abort listeners belong to this request, not the server producer. */
async function request<T>(
  path: string,
  method: "GET" | "POST",
  body: unknown,
  signal: AbortSignal | undefined,
  consume: (r: Response) => Promise<T>,
  ms = 10000,
): Promise<T> {
  const controller = new AbortController();
  const abort = () => controller.abort();
  if (signal?.aborted) controller.abort();
  signal?.addEventListener("abort", abort, { once: true });
  const timer = setTimeout(abort, ms);
  try {
    const response = await fetch(base + path, {
      method,
      headers: {
        Accept: path.includes("/events?")
          ? "text/event-stream"
          : "application/json",
        ...(method === "POST" ? { "Content-Type": "application/json" } : {}),
      },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      signal: controller.signal,
      cache: "no-store",
      redirect: "error",
    });
    if (!response.ok) {
      const value = await jsonBody(response);
      if (value && typeof value === "object" && !Array.isArray(value)) {
        const record = value as Record<string, unknown>;
        if (
          Object.keys(record).length === 2 &&
          Object.hasOwn(record, "code") &&
          typeof record.message === "string" &&
          chatCodes.includes(record.code as ChatCode)
        ) {
          const code = record.code as ChatCode;
          const definite =
            [409, 422, 429, 413].includes(response.status) &&
            !["CHAT_COMMIT_UNCERTAIN", "CHAT_STORAGE_ERROR"].includes(code);
          throw new ChatRequestError(code, definite);
        }
      }
      throw new Error("Chat request failed.");
    }
    const statuses =
      method === "GET"
        ? [200]
        : path === "/sessions"
          ? [200, 201]
          : path.endsWith("/turns")
            ? [200, 202]
            : [200];
    if (!statuses.includes(response.status)) {
      await response.body?.cancel();
      return invalid();
    }
    return await consume(response);
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", abort);
    controller.abort();
  }
}
async function jsonBody(response: Response): Promise<unknown> {
  if (
    response.headers.get("content-type")?.split(";")[0].trim() !==
      "application/json" ||
    !response.body
  ) {
    await response.body?.cancel();
    return invalid();
  }
  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let size = 0;
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      size += value.length;
      if (size > JSON_LIMIT) invalid();
      chunks.push(value);
    }
    const bytes = new Uint8Array(size);
    let offset = 0;
    for (const chunk of chunks) {
      bytes.set(chunk, offset);
      offset += chunk.length;
    }
    return decodeJSON(bytes);
  } finally {
    await reader.cancel().catch(() => undefined);
    reader.releaseLock();
  }
}
const json = (
  path: string,
  method: "GET" | "POST" = "GET",
  body?: unknown,
  signal?: AbortSignal,
) => request(path, method, body, signal, jsonBody);
function boundTurn(value: unknown, id: string) {
  const t = parseTurn(value);
  if (t.id !== id) invalid();
  return t;
}
export function bindSubmission(
  value: unknown,
  session: string,
  request: string,
  sequence: number,
  text: string,
) {
  const t = parseTurn(value);
  if (
    t.session_id !== session ||
    t.request_id !== request ||
    t.sequence !== sequence + 1 ||
    t.user_text !== text
  )
    invalid();
  return t;
}
export const chatClient = {
  async runtime(signal?: AbortSignal) {
    return parseRuntime(await json("/runtime", "GET", undefined, signal));
  },
  async sessions(signal?: AbortSignal) {
    return parseSessions(await json("/sessions", "GET", undefined, signal));
  },
  async start(runtime: ChatRuntime, request: string, locale: "en" | "ko") {
    uuid(request);
    if (!runtime.supported || !runtime.profile) invalid();
    const profile = runtime.profile;
    const bind = (s: ChatSession) => {
      if (
        s.request_id !== request ||
        s.settings_revision !== runtime.settings_revision ||
        s.profile_id !== profile.id ||
        s.model !== profile.model ||
        s.endpoint !== profile.endpoint ||
        s.streaming !== profile.streaming ||
        s.locale !== locale
      )
        invalid();
      return s;
    };
    try {
      return bind(
        parseSession(
          await json("/sessions", "POST", {
            request_id: request,
            settings_revision: runtime.settings_revision,
            profile_id: profile.id,
            approved_endpoint: profile.endpoint,
            locale,
          }),
        ),
      );
    } catch (error) {
      if (error instanceof ChatRequestError && error.definite) throw error;
      const found = (await chatClient.sessions()).find(
        (s) => s.request_id === request,
      );
      if (!found) invalid();
      return bind(found);
    }
  },
  async history(id: string, before?: number, signal?: AbortSignal) {
    uuid(id);
    if (
      before !== undefined &&
      (!Number.isSafeInteger(before) || before < 1 || before > 65)
    )
      invalid();
    const result = parseHistory(
      await json(
        `/sessions/${id}${before === undefined ? "" : `?before_sequence=${before}`}`,
        "GET",
        undefined,
        signal,
      ),
    );
    if (
      result.session.id !== id ||
      (before !== undefined && result.turns.some((t) => t.sequence >= before))
    )
      invalid();
    const last = Math.min(
      result.session.sequence,
      before === undefined ? result.session.sequence : before - 1,
    );
    const count = Math.min(2, last),
      first = last - count + 1;
    if (
      result.turns.length !== count ||
      result.turns.some((t, i) => t.sequence !== first + i) ||
      result.next_before_sequence !== (count > 0 && first > 1 ? first : null)
    )
      invalid();
    return result;
  },
  async turn(id: string, signal?: AbortSignal) {
    uuid(id);
    return boundTurn(await json(`/turns/${id}`, "GET", undefined, signal), id);
  },
  async byRequest(id: string, signal?: AbortSignal) {
    uuid(id);
    const t = parseTurn(
      await json(`/turns/by-request/${id}`, "GET", undefined, signal),
    );
    if (t.request_id !== id) invalid();
    return t;
  },
  async submit(
    session: string,
    request: string,
    sequence: number,
    text: string,
  ) {
    uuid(session);
    uuid(request);
    if (
      !Number.isSafeInteger(sequence) ||
      sequence < 0 ||
      sequence >= 64 ||
      !validText(text, 8192, true)
    )
      invalid();
    // Never attach a replaceable view signal to the submit acknowledgement.
    try {
      return bindSubmission(
        await json(`/sessions/${session}/turns`, "POST", {
          request_id: request,
          expected_sequence: sequence,
          text,
        }),
        session,
        request,
        sequence,
        text,
      );
    } catch (error) {
      if (error instanceof ChatRequestError && error.definite) throw error;
      return bindSubmission(
        await chatClient.byRequest(request),
        session,
        request,
        sequence,
        text,
      );
    }
  },
  async stop(id: string) {
    uuid(id);
    // Cancel acknowledgement is not remote-GPU-stop confirmation. Always read back.
    let acknowledgement: ChatTurn | null = null;
    try {
      acknowledgement = boundTurn(
        await json(`/turns/${id}/cancel`, "POST", {}),
        id,
      );
    } catch {
      /* GET is safe even if the cancel acknowledgement was lost. */
    }
    const readback = await chatClient.turn(id);
    return acknowledgement
      ? reconcileTurn(acknowledgement, readback)
      : readback;
  },
};
export async function observeTurn(
  initial: ChatTurn,
  signal: AbortSignal,
  update: (turn: ChatTurn) => void,
  streaming = true,
): Promise<ChatTurn> {
  if (terminal(initial)) return initial;
  const events = new ChatEvents(initial.id, streaming);
  let latest = initial;
  try {
    return await request(
      `/turns/${initial.id}/events?after=${initial.revision}`,
      "GET",
      undefined,
      signal,
      async (response) => {
        if (
          response.headers.get("content-type")?.split(";")[0].trim() !==
            "text/event-stream" ||
          !response.body
        ) {
          await response.body?.cancel();
          return invalid();
        }
        const reader = response.body.getReader();
        const decoder = new TextDecoder("utf-8", {
          fatal: true,
          ignoreBOM: true,
        });
        // A fixed byte buffer makes admission linear even for one-byte chunks.
        // Decode complete frames fatally: UTF-8 code points may cross any read.
        const buffer = new Uint8Array(FRAME_LIMIT);
        let used = 0,
          size = 0;
        try {
          while (true) {
            const { done, value } = await reader.read();
            if (signal.aborted) throw new Error("Detached.");
            if (done) return invalid();
            size += value.length;
            if (size > 2097152) invalid();
            for (const byte of value) {
              if (used === buffer.length) invalid();
              buffer[used++] = byte;
              if (byte !== 10) continue;
              const lastStart = used - (buffer[used - 2] === 13 ? 2 : 1);
              if (lastStart === 0 || buffer[lastStart - 1] !== 10) continue;
              const frameEnd =
                lastStart - (buffer[lastStart - 2] === 13 ? 2 : 1);
              const frame = decoder.decode(buffer.subarray(0, frameEnd));
              used = 0;
              const lines = frame.split(/\r?\n/);
              if (
                lines.length !== 2 ||
                lines[0] !== "event: chat" ||
                !lines[1].startsWith("data: ")
              )
                invalid();
              const data = lines[1].slice(6);
              if (utf8Length(data) > JSON_LIMIT) invalid();
              const next = events.apply(parseJSON(data));
              reconcileTurn(latest, next);
              latest = next;
              update(next);
              if (terminal(next)) return next;
            }
          }
        } finally {
          await reader.cancel().catch(() => undefined);
          reader.releaseLock();
        }
      },
      125000,
    );
  } catch {
    if (signal.aborted) throw new Error("Detached.");
    const readback = await chatClient.turn(initial.id, signal);
    reconcileTurn(latest, readback);
    update(readback);
    return readback;
  }
}
