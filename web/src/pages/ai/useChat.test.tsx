import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { useChat } from "./useChat";
import {
  response,
  runtimeFixture,
  session,
  sid,
  turn,
} from "./chat-test-fixtures";
afterEach(() => vi.unstubAllGlobals());

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}
const completed = {
  ...turn,
  revision: 3,
  status: "succeeded",
  assistant_text: "retained answer",
  finished_at: turn.created_at,
  transport: "closed",
  provider_stop: "unknown",
};
const retainedPage = {
  schema_version: 1,
  session: { ...session, active_turn_id: null },
  turns: [completed],
  next_before_sequence: null,
};

// Permanent F1: the independent probe's lost ACK -> reopen -> recovery -> Stop.
// Its intermediate assertions described the bug (suppressed open/uncertain=true);
// here completion must instead retire that request without adopting its stale view.
it.each(["stop-first", "recovery-first", "invalid", "unavailable"])(
  "F1: Stop remains usable during held recovery (%s), which releases its own lease",
  async (outcome) => {
    const recovery = deferred<Response>();
    const cancellation = deferred<Response>();
    let request = "",
      opened = false,
      recovering = false;
    const fetch = vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith("runtime")) return response(runtimeFixture);
      if (url.endsWith("sessions"))
        return response({ schema_version: 1, sessions: [] });
      if (url.endsWith(`/sessions/${sid}`)) {
        const page = opened
          ? {
              schema_version: 1,
              session,
              turns: [{ ...turn, request_id: request }],
              next_before_sequence: null,
            }
          : {
              schema_version: 1,
              session: { ...session, sequence: 0, active_turn_id: null },
              turns: [],
              next_before_sequence: null,
            };
        opened = true;
        return response(page);
      }
      if (url.endsWith("/turns") && init?.method === "POST") {
        request = JSON.parse(init.body as string).request_id;
        throw new Error("lost ACK");
      }
      if (url.includes("by-request")) {
        if (!recovering) throw new Error("readback unavailable");
        return recovery.promise;
      }
      if (url.includes("events?")) throw new Error("observer detached");
      if (url.endsWith("/cancel")) return cancellation.promise;
      return response({
        ...(recovering ? completed : turn),
        request_id: request,
      });
    });
    vi.stubGlobal("fetch", fetch);
    const { result } = renderHook(() => useChat("en", true));
    await waitFor(() => expect(result.current.runtime).not.toBeNull());
    await act(() => result.current.open(sid));
    act(() => result.current.setInput("hello"));
    await act(() => result.current.send());
    expect(result.current.uncertain).toBe(true);
    await act(() => result.current.open(sid));
    expect(result.current.session?.active_turn_id).toBe(turn.id);
    recovering = true;
    let recoveringRequest!: Promise<void>, stop!: Promise<void>;
    act(() => {
      recoveringRequest = result.current.recoverSubmission();
    });
    expect(result.current.busy).toBe(true);
    act(() => {
      stop = result.current.stop();
    });
    expect(
      fetch.mock.calls.filter(([url]) => url.endsWith("/cancel")),
    ).toHaveLength(1);
    expect(result.current.stopping).toBe(true);
    const settleRecovery = async () => {
      if (outcome === "unavailable") recovery.reject(new Error("offline"));
      else
        recovery.resolve(
          response({
            ...completed,
            // A same-request foreign binding must NOT retire pending uncertainty.
            ...(outcome === "invalid" ? { user_text: "wrong content" } : {}),
            request_id: request,
          }),
        );
      await recoveringRequest;
    };
    if (outcome === "recovery-first") {
      await act(settleRecovery);
      expect(result.current.stopping).toBe(true);
      expect(result.current.phase).toBe("cancel_requested");
      expect(result.current.currentTurn?.status).toBe("accepted");
    }
    await act(async () => {
      cancellation.resolve(response({ ...completed, request_id: request }));
      await stop;
    });
    if (outcome !== "recovery-first") await act(settleRecovery);
    expect(result.current.stopping).toBe(false);
    expect(result.current.busy).toBe(false);
    expect(result.current.uncertain).toBe(
      outcome === "invalid" || outcome === "unavailable",
    );
    expect(result.current.currentTurn).toEqual({
      ...completed,
      request_id: request,
    });
    expect(result.current.phase).toBe("succeeded");
    expect(result.current.input).toBe("hello");
    const calls = fetch.mock.calls.filter(([url]) =>
      url.endsWith(`/sessions/${sid}`),
    ).length;
    await act(() => result.current.open(sid));
    expect(
      fetch.mock.calls.filter(([url]) => url.endsWith(`/sessions/${sid}`)),
    ).toHaveLength(calls + 1);
    expect(
      fetch.mock.calls.filter(
        ([url, init]) => url.endsWith("/turns") && init?.method === "POST",
      ),
    ).toHaveLength(1);
  },
);

// Permanent F2, including success and transport-unknown exits of the same owner.
it.each(["refused", "unknown", "success"])(
  "F2: new session retires held history read on %s without losing input or stale-view fencing",
  async (outcome) => {
    const history = deferred<Response>();
    const creation = deferred<Response>();
    let slow = false,
      historySignal: AbortSignal | null | undefined,
      request = "";
    const other = "44444444-4444-4444-8444-444444444444";
    const fetch = vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith("runtime")) return response(runtimeFixture);
      if (url.endsWith("sessions") && init?.method === "GET")
        return response({ schema_version: 1, sessions: [] });
      if (url.endsWith("sessions") && init?.method === "POST") {
        request = JSON.parse(init.body as string).request_id;
        return creation.promise;
      }
      if (slow) {
        historySignal = init?.signal;
        return history.promise;
      }
      return response(retainedPage);
    });
    vi.stubGlobal("fetch", fetch);
    const { result } = renderHook(() => useChat("en", true));
    await waitFor(() => expect(result.current.runtime).not.toBeNull());
    await act(() => result.current.open(sid));
    act(() => result.current.setInput("unsent"));
    slow = true;
    let reading!: Promise<void>, starting!: Promise<boolean>;
    act(() => {
      reading = result.current.open(sid);
    });
    expect(result.current.reading).toBe(true);
    act(() => {
      starting = result.current.start();
    });
    expect(historySignal?.aborted).toBe(true);
    await act(async () => {
      if (outcome === "unknown") creation.reject(new Error("lost ACK"));
      else if (outcome === "refused")
        creation.resolve(
          response(
            { code: "CHAT_RETENTION_FULL", message: "Chat history is full." },
            409,
          ),
        );
      else
        creation.resolve(
          response(
            {
              ...session,
              id: other,
              request_id: request,
              sequence: 0,
              active_turn_id: null,
            },
            201,
          ),
        );
      await starting;
      // Even a transport ignoring abort and delivering a valid stale page is fenced.
      history.resolve(response(retainedPage));
      await reading;
    });
    expect(result.current.phase).toBe(
      outcome === "success"
        ? "ready"
        : outcome === "refused"
          ? "rejected"
          : "unknown-session",
    );
    expect(result.current.input).toBe("unsent");
    expect(result.current.session?.id).toBe(
      outcome === "success" ? other : sid,
    );
    expect(result.current.turns).toEqual(
      outcome === "success" ? [] : [completed],
    );
    expect(result.current.uncertainSession).toBe(outcome === "unknown");
    expect(result.current.errorCode).toBe(
      outcome === "refused" ? "CHAT_RETENTION_FULL" : null,
    );
    expect(result.current.busy).toBe(false);
    expect(result.current.reading).toBe(false);
    if (outcome === "unknown") {
      await act(() => result.current.start());
      expect(
        fetch.mock.calls.filter(([, init]) => init?.method === "POST"),
      ).toHaveLength(1);
    }
  },
);

it("refresh retires its superseded history reader, including an ignored abort", async () => {
  const old = deferred<Response>();
  let slow = false;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      if (url.endsWith("runtime")) return response(runtimeFixture);
      if (url.endsWith("sessions"))
        return response({ schema_version: 1, sessions: [] });
      return slow ? old.promise : response(retainedPage);
    }),
  );
  const { result } = renderHook(() => useChat("en", true));
  await waitFor(() => expect(result.current.runtime).not.toBeNull());
  await act(() => result.current.open(sid));
  act(() => result.current.setInput("unsent"));
  slow = true;
  let read!: Promise<void>;
  act(() => {
    read = result.current.open(sid);
  });
  await act(() => result.current.refresh());
  expect(result.current.reading).toBe(false);
  await act(async () => {
    old.resolve(response(retainedPage));
    await read;
  });
  expect(result.current.turns).toEqual([completed]);
  expect(result.current.input).toBe("unsent");
});

it("a superseded history finally cannot release a newer reader", async () => {
  const old = deferred<Response>(),
    newer = deferred<Response>();
  let calls = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      if (url.endsWith("runtime")) return response(runtimeFixture);
      if (url.endsWith("sessions"))
        return response({ schema_version: 1, sessions: [] });
      return ++calls === 1 ? old.promise : newer.promise;
    }),
  );
  const { result } = renderHook(() => useChat("en", true));
  await waitFor(() => expect(result.current.runtime).not.toBeNull());
  let first!: Promise<void>, second!: Promise<void>;
  act(() => {
    first = result.current.open(sid);
  });
  act(() => {
    second = result.current.open(sid);
  });
  await act(async () => {
    old.resolve(response(retainedPage));
    await first;
  });
  expect(result.current.reading).toBe(true);
  expect(result.current.turns).toEqual([]);
  await act(async () => {
    newer.resolve(response(retainedPage));
    await second;
  });
  expect(result.current.reading).toBe(false);
  expect(result.current.turns).toEqual([completed]);
});
it.each(["accepted", "refused", "unknown"])(
  "a session creation superseded by Stop releases only its own %s request",
  async (outcome) => {
    const creation = deferred<Response>();
    let request = "";
    const other = "44444444-4444-4444-8444-444444444444";
    const fetch = vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith("runtime")) return response(runtimeFixture);
      if (url.endsWith("sessions") && init?.method === "GET")
        return response({ schema_version: 1, sessions: [] });
      if (url.endsWith("sessions") && init?.method === "POST") {
        request = JSON.parse(init.body as string).request_id;
        return creation.promise;
      }
      if (url.endsWith(`/sessions/${sid}`))
        return response({
          schema_version: 1,
          session,
          turns: [turn],
          next_before_sequence: null,
        });
      if (url.includes("events?")) throw new Error("detached");
      return response(url.endsWith("/cancel") || request ? completed : turn);
    });
    vi.stubGlobal("fetch", fetch);
    const { result } = renderHook(() => useChat("en", true));
    await waitFor(() => expect(result.current.runtime).not.toBeNull());
    await act(() => result.current.open(sid));
    act(() => result.current.setInput("unsent"));
    let starting!: Promise<boolean>;
    act(() => {
      starting = result.current.start();
    });
    await act(() => result.current.stop());
    // The independent Stop request must not release a still-running mutation.
    expect(result.current.busy).toBe(true);
    await act(async () => {
      if (outcome === "unknown") creation.reject(new Error("lost ACK"));
      else if (outcome === "refused")
        creation.resolve(
          response({ code: "CHAT_RETENTION_FULL", message: "Full" }, 409),
        );
      else
        creation.resolve(
          response(
            {
              ...session,
              id: other,
              request_id: request,
              sequence: 0,
              active_turn_id: null,
            },
            201,
          ),
        );
      await starting;
    });
    expect(result.current.busy).toBe(false);
    expect(result.current.uncertainSession).toBe(outcome === "unknown");
    expect(result.current.session?.id).toBe(sid);
    expect(result.current.currentTurn).toEqual(completed);
    expect(result.current.phase).toBe("succeeded");
    expect(result.current.input).toBe("unsent");
  },
);

it("an older Stop finally cannot clear a newer Stop lease or overwrite its view", async () => {
  const first = deferred<Response>(),
    second = deferred<Response>();
  const other = "44444444-4444-4444-8444-444444444444";
  const otherTurn = "55555555-5555-4555-8555-555555555555";
  const fetch = vi.fn(async (url: string) => {
    if (url.endsWith("runtime")) return response(runtimeFixture);
    if (url.endsWith("sessions"))
      return response({ schema_version: 1, sessions: [] });
    const next = url.includes(other) || url.includes(otherTurn);
    const active = {
      ...turn,
      id: next ? otherTurn : turn.id,
      session_id: next ? other : sid,
    };
    if (url.includes("/sessions/"))
      return response({
        schema_version: 1,
        session: {
          ...session,
          id: active.session_id,
          active_turn_id: active.id,
        },
        turns: [active],
        next_before_sequence: null,
      });
    if (url.endsWith("/cancel")) return next ? second.promise : first.promise;
    if (url.includes("events?")) throw new Error("detached");
    return response({
      ...completed,
      id: active.id,
      session_id: active.session_id,
    });
  });
  vi.stubGlobal("fetch", fetch);
  const { result } = renderHook(() => useChat("en", true));
  await waitFor(() => expect(result.current.runtime).not.toBeNull());
  // Hold observations at accepted so both explicit Stops are admitted.
  // A failed events readback is deliberately unavailable until cancel starts.
  const implementation = fetch.getMockImplementation()!;
  const cancelling = new Set<string>();
  fetch.mockImplementation(async (url: string) => {
    if (url.endsWith("/cancel")) cancelling.add(url.replace("/cancel", ""));
    if (
      url.includes("/turns/") &&
      !url.includes("events?") &&
      !url.endsWith("/cancel") &&
      !cancelling.has(url)
    )
      throw new Error("readback unavailable");
    return implementation(url);
  });
  await act(() => result.current.open(sid));
  let old!: Promise<void>, newer!: Promise<void>;
  act(() => {
    old = result.current.stop();
  });
  await act(() => result.current.open(other));
  act(() => {
    newer = result.current.stop();
  });
  await act(async () => {
    first.resolve(response(completed));
    await old;
  });
  expect(result.current.stopping).toBe(true);
  expect(result.current.session?.id).toBe(other);
  expect(result.current.currentTurn?.status).toBe("accepted");
  await act(async () => {
    second.resolve(
      response({ ...completed, id: otherTurn, session_id: other }),
    );
    await newer;
  });
  expect(result.current.stopping).toBe(false);
  expect(result.current.currentTurn?.id).toBe(otherTurn);
  expect(result.current.currentTurn?.status).toBe("succeeded");
});

it("unknown submit keeps input, blocks resend, and explicit request readback accepts once", async () => {
  let readback = false,
    request = "";
  const fetch = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith("runtime")) return response(runtimeFixture);
    if (url.endsWith("sessions"))
      return response({ schema_version: 1, sessions: [] });
    if (url === `/api/v1/chat/sessions/${sid}`)
      return response({
        schema_version: 1,
        session: { ...session, sequence: 0, active_turn_id: null },
        turns: [],
        next_before_sequence: null,
      });
    if (url.endsWith("/turns")) {
      request = JSON.parse(init!.body as string).request_id;
      throw new Error("ACK lost");
    }
    if (url.includes("by-request") && readback)
      return response({
        ...turn,
        request_id: request,
        status: "succeeded",
        assistant_text: "saved",
        finished_at: turn.created_at,
        transport: "closed",
        provider_stop: "unknown",
      });
    throw new Error("unknown");
  });
  vi.stubGlobal("fetch", fetch);
  const { result } = renderHook(() => useChat("en", true));
  await waitFor(() => expect(result.current.runtime).not.toBeNull());
  await act(() => result.current.open(sid));
  act(() => result.current.setInput("hello"));
  await act(() => result.current.send());
  expect(result.current.input).toBe("hello");
  expect(result.current.phase).toBe("unknown-send");
  await act(() => result.current.send());
  expect(fetch.mock.calls.filter((c) => c[1]?.method === "POST")).toHaveLength(
    1,
  );
  readback = true;
  await act(() => result.current.recoverSubmission());
  expect(result.current.input).toBe("");
  expect(result.current.turns[0].assistant_text).toBe("saved");
});
it("a definite refusal preserves input and exposes its fixed code without claiming unknown acceptance", async () => {
  const fetch = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith("runtime")) return response(runtimeFixture);
    if (url.endsWith("sessions"))
      return response({ schema_version: 1, sessions: [] });
    if (url === `/api/v1/chat/sessions/${sid}`)
      return response({
        schema_version: 1,
        session: { ...session, sequence: 0, active_turn_id: null },
        turns: [],
        next_before_sequence: null,
      });
    if (init?.method === "POST")
      return response(
        {
          code: "CHAT_CONTEXT_LIMIT",
          message: "Never reflect this arbitrary body",
        },
        409,
      );
    throw new Error("No readback for definitive refusal");
  });
  vi.stubGlobal("fetch", fetch);
  const { result } = renderHook(() => useChat("en", true));
  await waitFor(() => expect(result.current.runtime).not.toBeNull());
  await act(() => result.current.open(sid));
  act(() => result.current.setInput("hello"));
  await act(() => result.current.send());
  expect(result.current.phase).toBe("rejected");
  expect(result.current.errorCode).toBe("CHAT_CONTEXT_LIMIT");
  expect(result.current.input).toBe("hello");
  expect(result.current.uncertain).toBe(false);
  expect(fetch.mock.calls.some((c) => c[0].includes("by-request"))).toBe(false);
});
it("unknown session creation cannot be replayed by clicking confirm again", async () => {
  const fetch = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith("runtime")) return response(runtimeFixture);
    if (url.endsWith("sessions") && init?.method === "GET")
      return response({ schema_version: 1, sessions: [] });
    throw new Error("lost create ACK");
  });
  vi.stubGlobal("fetch", fetch);
  const { result } = renderHook(() => useChat("en", true));
  await waitFor(() => expect(result.current.runtime).not.toBeNull());
  await act(() => result.current.start());
  expect(result.current.phase).toBe("unknown-session");
  await act(() => result.current.start());
  expect(fetch.mock.calls.filter((c) => c[1]?.method === "POST")).toHaveLength(
    1,
  );
  expect(result.current.uncertainSession).toBe(true);
});
it("unmount at submit/ack detaches only and never cancels or resubmits", async () => {
  let resolve!: (r: Response) => void,
    request = "";
  const fetch = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith("runtime")) return response(runtimeFixture);
    if (url.endsWith("sessions"))
      return response({ schema_version: 1, sessions: [] });
    if (url === `/api/v1/chat/sessions/${sid}`)
      return response({
        schema_version: 1,
        session: { ...session, sequence: 0, active_turn_id: null },
        turns: [],
        next_before_sequence: null,
      });
    request = JSON.parse(init!.body as string).request_id;
    return new Promise<Response>((r) => {
      resolve = r;
    });
  });
  vi.stubGlobal("fetch", fetch);
  const { result, unmount } = renderHook(() => useChat("en", true));
  await waitFor(() => expect(result.current.runtime).not.toBeNull());
  await act(() => result.current.open(sid));
  act(() => result.current.setInput("hello"));
  let sent!: Promise<void>;
  act(() => {
    sent = result.current.send();
  });
  const submitSignal = fetch.mock.calls.at(-1)![1]!.signal;
  unmount();
  expect(submitSignal?.aborted).toBe(false);
  await act(async () => {
    resolve(response({ ...turn, request_id: request }));
    await sent;
  });
  expect(fetch.mock.calls.filter((c) => c[1]?.method === "POST")).toHaveLength(
    1,
  );
  expect(
    fetch.mock.calls.some(
      (c) => c[0].endsWith("cancel") || c[0].includes("events"),
    ),
  ).toBe(false);
});
it("late cancel readback cannot overwrite another conversation or leave its controls stuck", async () => {
  const other = "44444444-4444-4444-8444-444444444444";
  let cancel!: (r: Response) => void;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      if (url.endsWith("runtime")) return response(runtimeFixture);
      if (url.endsWith("sessions"))
        return response({ schema_version: 1, sessions: [] });
      if (url.endsWith(`/sessions/${sid}`))
        return response({
          schema_version: 1,
          session,
          turns: [turn],
          next_before_sequence: null,
        });
      if (url.endsWith(`/sessions/${other}`))
        return response({
          schema_version: 1,
          session: { ...session, id: other, sequence: 0, active_turn_id: null },
          turns: [],
          next_before_sequence: null,
        });
      if (url.endsWith("/cancel"))
        return new Promise<Response>((r) => {
          cancel = r;
        });
      if (url.includes("events?")) throw new Error("detached test");
      return response(turn);
    }),
  );
  const { result } = renderHook(() => useChat("en", true));
  await waitFor(() => expect(result.current.runtime).not.toBeNull());
  await act(() => result.current.open(sid));
  let stopped!: Promise<void>;
  act(() => {
    stopped = result.current.stop();
  });
  await act(() => result.current.open(other));
  await act(async () => {
    cancel(response(turn));
    await stopped;
  });
  expect(result.current.session?.id).toBe(other);
  expect(result.current.turns).toEqual([]);
  expect(result.current.stopping).toBe(false);
});
it("late history read cannot overwrite the selected conversation", async () => {
  let resolve!: (r: Response) => void;
  const other = "44444444-4444-4444-8444-444444444444";
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      if (url.endsWith("runtime")) return response(runtimeFixture);
      if (url.endsWith("sessions"))
        return response({ schema_version: 1, sessions: [] });
      if (url.endsWith(sid))
        return new Promise<Response>((r) => {
          resolve = r;
        });
      return response({
        schema_version: 1,
        session: { ...session, id: other, sequence: 0, active_turn_id: null },
        turns: [],
        next_before_sequence: null,
      });
    }),
  );
  const { result } = renderHook(() => useChat("en", true));
  await waitFor(() => expect(result.current.runtime).not.toBeNull());
  let old!: Promise<void>;
  act(() => {
    old = result.current.open(sid);
  });
  await act(() => result.current.open(other));
  await act(async () => {
    resolve(
      response({
        schema_version: 1,
        session,
        turns: [turn],
        next_before_sequence: null,
      }),
    );
    await old;
  });
  expect(result.current.session?.id).toBe(other);
  expect(result.current.turns).toEqual([]);
});
