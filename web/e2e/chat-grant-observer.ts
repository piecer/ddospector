import { createHash } from "node:crypto";
import {
  check,
  integer,
  object,
  parseGrant,
  timeKey,
} from "../src/pages/ai/chat-tool-wire";
import { uuid, validText } from "../src/pages/ai/chat-wire";
import { parseJSON, utf8Length } from "../src/pages/scenarios/json";
import type { ChatSession } from "../src/pages/ai/chat-types";
import type {
  RequestedAuthority,
  ToolGrant,
} from "../src/pages/ai/chat-tool-types";

export type ObservedPost = { method: string; path: string; body: unknown };
export type GrantObserverFact = {
  source: "observed-browser-POST" | "persisted-grant-by-request-GET";
  stage: "original" | "readback-start" | "readback-response" | "validated";
  [key: string]: unknown;
};
export type GrantObservationInput = {
  now?: () => number;
  clock?: () => number;
  record?: (fact: GrantObserverFact) => void;
  post: ObservedPost & { status: number };
  session: Pick<
    ChatSession,
    "id" | "sequence" | "profile_id" | "settings_revision"
  >;
  prompt: string;
  authority: RequestedAuthority;
  observedTurn: ObservedPost;
  get: (
    path: string,
    options: {
      timeout: number;
      maxRetries: 0;
      maxRedirects: 0;
    },
  ) => Promise<{ status: number; body: string }>;
};
export type GrantObservation = {
  source: "persisted-grant-by-request-GET";
  originalResponseBody: "not-observed";
  grant: ToolGrant;
  rawReadback: string;
};

export async function observePersistedGrant(
  input: GrantObservationInput,
): Promise<GrantObservation> {
  // One local 15s observation budget (the existing expect budget), nested in
  // the unchanged Playwright test deadline. Covers GET and adapter body read.
  const clock = input.clock ?? (() => performance.now());
  const deadline = clock() + 15_000;
  let expired = false;
  const remaining = () => {
    const left = deadline - clock();
    if (expired || left <= 0)
      throw new Error("Grant observer deadline exceeded");
    return Math.ceil(left);
  };
  let timer: ReturnType<typeof setTimeout> | undefined;
  const timeout = new Promise<never>((_resolve, reject) => {
    timer = setTimeout(() => {
      expired = true;
      reject(new Error("Grant observer deadline exceeded"));
    }, 15_000);
  });
  try {
    return await Promise.race([readOnce(input, remaining), timeout]);
  } finally {
    clearTimeout(timer);
  }
}

async function readOnce(
  input: GrantObservationInput,
  remaining: () => number,
): Promise<GrantObservation> {
  const { session, prompt, authority, observedTurn } = input;
  input.record?.({
    source: "observed-browser-POST",
    stage: "original",
    originalResponseBody: "not-observed",
    post: input.post,
    session,
    observedTurn,
    prompt,
    authority,
  });
  check(
    input.post.method === "POST" &&
      input.post.path === "/api/v1/chat/tool-grants" &&
      input.post.status === 201,
  );
  check(authority === "agent_v1" || authority === "target_create_v2");
  const target = authority === "target_create_v2";
  const post = object(
    input.post.body,
    "request_id session_id turn_request_id expected_sequence text" +
      (target ? " schema_version scope" : ""),
  );
  [post.request_id, post.session_id, post.turn_request_id, session.id].forEach(
    uuid,
  );
  integer(session.sequence, 0, 63);
  integer(session.settings_revision);
  check(validText(prompt, 8192, true));
  check(
    post.session_id === session.id &&
      post.expected_sequence === session.sequence &&
      post.text === prompt,
  );
  if (target)
    check(post.schema_version === 2 && post.scope === "target_create");
  check(
    observedTurn.method === "POST" &&
      observedTurn.path === `/api/v1/chat/sessions/${session.id}/tool-turns`,
  );
  const turn = object(
    observedTurn.body,
    "request_id expected_sequence text grant_id",
  );
  uuid(turn.request_id);
  uuid(turn.grant_id);
  check(
    turn.request_id === post.turn_request_id &&
      turn.expected_sequence === session.sequence &&
      turn.text === prompt,
  );

  // This is a single independent persisted read, never a POST retry or a
  // replacement for the historical POST response body. No write API is exposed.
  const path = `/api/v1/chat/tool-grants/by-request/${post.request_id}`;
  const source = "persisted-grant-by-request-GET" as const;
  input.record?.({ source, stage: "readback-start", path });
  const response = await input.get(path, {
    timeout: remaining(),
    maxRetries: 0,
    maxRedirects: 0,
  });
  remaining();
  input.record?.({ source, stage: "readback-response", path, ...response });
  check(response.status === 200 && utf8Length(response.body) <= 8192);
  const grant = parseGrant(parseJSON(response.body));
  check(grant.schema_version === (target ? 2 : 1));
  check(
    grant.request_id === post.request_id &&
      grant.session_id === session.id &&
      grant.turn_request_id === post.turn_request_id &&
      grant.id === turn.grant_id &&
      grant.expected_sequence === session.sequence &&
      grant.profile_id === session.profile_id &&
      grant.settings_revision === session.settings_revision &&
      grant.text_sha256 ===
        createHash("sha256").update(JSON.stringify(prompt)).digest("hex"),
  );
  check(grant.status === "pending" || grant.status === "consumed");
  // Match the producer's exact five-minute lifetime, including microseconds.
  check(
    Date.parse(grant.expires_at) - Date.parse(grant.created_at) === 300_000 &&
      timeKey(grant.expires_at).slice(19) ===
        timeKey(grant.created_at).slice(19),
  );
  // Consumed is historical state, not a currently spendable grant. Do not
  // reject it just because the original grant lifetime has since elapsed.
  if (grant.status === "pending")
    check(
      timeKey(new Date((input.now ?? Date.now)()).toISOString()) <
        timeKey(grant.expires_at),
    );
  remaining();
  input.record?.({ source, stage: "validated", path, status: grant.status });
  remaining();
  return {
    source: "persisted-grant-by-request-GET",
    originalResponseBody: "not-observed",
    grant,
    rawReadback: response.body,
  };
}
