import { setTimeout as nativeWait } from "node:timers/promises";
import { afterEach, expect, it, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { useToolTranscript } from "./useToolTranscript";
import { parseTurn } from "./chat-wire";
import { turn, response, tid, rid } from "./chat-test-fixtures";
import { call, savedCall, transcript } from "./chat-tool-test-fixtures";
const flush = async (ms = 0) => {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
    await nativeWait(15);
  });
};
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});
it("visibility detaches reads and resumes only when visible; unmount clears timers", async () => {
  vi.useFakeTimers();
  const visibility = vi
    .spyOn(document, "visibilityState", "get")
    .mockReturnValue("hidden");
  const fetch = vi.fn(async () => response(transcript));
  vi.stubGlobal("fetch", fetch);
  const { unmount } = renderHook(() =>
    useToolTranscript(parseTurn(turn), true, 0),
  );
  await flush(2000);
  expect(fetch).not.toHaveBeenCalled();
  visibility.mockReturnValue("visible");
  act(() => document.dispatchEvent(new Event("visibilitychange")));
  await flush();
  expect(fetch).toHaveBeenCalledTimes(1);
  visibility.mockReturnValue("hidden");
  act(() => document.dispatchEvent(new Event("visibilitychange")));
  await flush(2000);
  expect(fetch).toHaveBeenCalledTimes(1);
  unmount();
  expect(vi.getTimerCount()).toBe(0);
});
it("late old-view GET cannot replace a new visible turn and keeps its owned slot until retirement", async () => {
  vi.useFakeTimers();
  let oldRead: (r: Response) => void = () => undefined;
  const fetch = vi.fn(async (url: string) =>
    url.includes(tid)
      ? new Promise<Response>((resolve) => {
          oldRead = resolve;
        })
      : response({ ...transcript, turn_id: rid, calls: [] }),
  );
  vi.stubGlobal("fetch", fetch);
  const { result, rerender, unmount } = renderHook(
    ({ t }) => useToolTranscript(t, true, 0),
    { initialProps: { t: parseTurn(turn) } },
  );
  await flush();
  rerender({ t: parseTurn({ ...turn, id: rid }) });
  await flush(1000);
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(result.current.record).toBeNull();
  await act(async () => {
    oldRead(response(transcript));
    await nativeWait(15);
  });
  expect(result.current.record).toBeNull();
  await flush(500);
  expect(result.current.record?.turn_id).toBe(rid);
  unmount();
  expect(vi.getTimerCount()).toBe(0);
});
it("terminal observation needs a fresh completion-spaced GET, never the old inflight awaiting record, and stops after final synchronization", async () => {
  vi.useFakeTimers();
  const completions: ((r: Response) => void)[] = [];
  const fetch = vi.fn(() => new Promise<Response>((r) => completions.push(r)));
  vi.stubGlobal("fetch", fetch);
  const current = parseTurn(turn);
  const { result, rerender, unmount } = renderHook(
    ({ t }) => useToolTranscript(t, true, 0),
    { initialProps: { t: current } },
  );
  await flush();
  expect(fetch).toHaveBeenCalledTimes(1);
  rerender({
    t: parseTurn({
      ...turn,
      status: "cancelled",
      error_code: "CHAT_CANCELLED",
      transport: "closed",
      finished_at: turn.created_at,
    }),
  });
  await flush(1000);
  expect(fetch).toHaveBeenCalledTimes(1);
  await act(async () => {
    completions[0](response(transcript));
    await nativeWait(15);
  });
  await flush(499);
  expect(fetch).toHaveBeenCalledTimes(1);
  await flush(1);
  expect(fetch).toHaveBeenCalledTimes(2);
  await act(async () => {
    completions[1](
      response({ ...transcript, revision: 2, calls: [savedCall] }),
    );
    await nativeWait(15);
  });
  await flush(5000);
  expect(fetch).toHaveBeenCalledTimes(2);
  expect(result.current.record?.calls[0].status).toBe("succeeded");
  expect(result.current.stale).toBe(false);
  unmount();
  expect(vi.getTimerCount()).toBe(0);
});
it("final companion with pending calls is unknown; GET-only retry may recover without any POST", async () => {
  vi.useFakeTimers();
  let saved = false;
  const fetch = vi.fn(async () =>
    response(
      saved ? { ...transcript, revision: 2, calls: [savedCall] } : transcript,
    ),
  );
  vi.stubGlobal("fetch", fetch);
  const { result, unmount } = renderHook(() =>
    useToolTranscript(
      parseTurn({
        ...turn,
        status: "cancelled",
        error_code: "CHAT_CANCELLED",
        finished_at: turn.created_at,
        transport: "closed",
      }),
      true,
      0,
    ),
  );
  await flush();
  expect(result.current.stale).toBe(true);
  await flush(3000);
  expect(fetch).toHaveBeenCalledTimes(1);
  saved = true;
  act(() => result.current.refresh());
  await flush();
  expect(result.current.record?.calls[0].status).toBe("succeeded");
  unmount();
});
it("navigating while a decision ACK is delayed does not re-adopt the old call or lock the new view", async () => {
  vi.useFakeTimers();
  let decisionResolve: (r: Response) => void = () => undefined;
  const fetch = vi.fn(async (url: string, init?: RequestInit) => {
    if (init?.method === "POST")
      return new Promise<Response>((resolve) => {
        decisionResolve = resolve;
      });
    if (url === `/api/v1/chat/turns/${tid}/tools`) return response(transcript);
    return response({ ...transcript, turn_id: rid, calls: [] });
  });
  vi.stubGlobal("fetch", fetch);
  const { result, rerender, unmount } = renderHook(
    ({ t }) => useToolTranscript(t, true, 0),
    { initialProps: { t: parseTurn(turn) } },
  );
  await flush();
  act(() => {
    void result.current.decide(
      result.current.record!.calls[0],
      "approve",
      true,
    );
  });
  const input = JSON.parse(
    fetch.mock.calls.find(([, i]) => i?.method === "POST")![1]!.body as string,
  );
  rerender({ t: parseTurn({ ...turn, id: rid }) });
  await flush(500);
  await act(async () =>
    decisionResolve(
      response(
        {
          schema_version: 1,
          ...input,
          call_id: call.id,
          accepted_at: call.started_at,
        },
        201,
      ),
    ),
  );
  expect(result.current.record?.turn_id).toBe(rid);
  expect(result.current.decisionState).toBe("idle");
  unmount();
  await flush(2000);
  expect(vi.getTimerCount()).toBe(0);
});
it("lost decision ACK stays GET-only across explicit view reload, never re-enabling approval", async () => {
  vi.useFakeTimers();
  const fetch = vi.fn(async (_url: string, init?: RequestInit) => {
    if (init?.method === "POST") throw Error("lost");
    return response(transcript);
  });
  vi.stubGlobal("fetch", fetch);
  const { result, rerender, unmount } = renderHook(
    ({ epoch }) => useToolTranscript(parseTurn(turn), true, epoch),
    { initialProps: { epoch: 0 } },
  );
  await flush();
  await act(async () => {
    void result.current.decide(
      result.current.record!.calls[0],
      "approve",
      true,
    );
    await nativeWait(15);
  });
  expect(result.current.decisionState).toBe("unknown");
  rerender({ epoch: 1 });
  await flush();
  await act(async () => {
    void result.current.decide(
      result.current.record!.calls[0],
      "approve",
      true,
    );
    await nativeWait(15);
  });
  expect(fetch.mock.calls.filter(([, i]) => i?.method === "POST")).toHaveLength(
    1,
  );
  expect(result.current.decisionBlocked).toBe(true);
  unmount();
});
it("explicit reload cannot forget a previously observed terminal receipt", async () => {
  vi.useFakeTimers();
  let old = false;
  const fetch = vi.fn(async () =>
    response(
      old ? transcript : { ...transcript, revision: 2, calls: [savedCall] },
    ),
  );
  vi.stubGlobal("fetch", fetch);
  const { result, rerender, unmount } = renderHook(
    ({ epoch }) => useToolTranscript(parseTurn(turn), true, epoch),
    { initialProps: { epoch: 0 } },
  );
  await flush();
  expect(result.current.record?.calls[0].status).toBe("succeeded");
  old = true;
  rerender({ epoch: 1 });
  await flush();
  expect(result.current.record?.calls[0].status).toBe("succeeded");
  expect(result.current.stale).toBe(true);
  unmount();
});
it("visible companion groups share one completion-spaced request slot", async () => {
  vi.useFakeTimers();
  const gate = { owner: null as symbol | null, completed: -Infinity };
  const useShared = useToolTranscript as (
    ...args: unknown[]
  ) => ReturnType<typeof useToolTranscript>;
  const fetch = vi.fn(async (url: string) =>
    response({
      ...transcript,
      turn_id: url.includes(tid) ? tid : rid,
      calls: [],
    }),
  );
  vi.stubGlobal("fetch", fetch);
  const { unmount } = renderHook(() => {
    useShared(parseTurn(turn), true, 0, undefined, undefined, gate);
    useShared(
      parseTurn({ ...turn, id: rid }),
      true,
      0,
      undefined,
      undefined,
      gate,
    );
  });
  await flush();
  expect(fetch).toHaveBeenCalledTimes(1);
  await flush(499);
  expect(fetch).toHaveBeenCalledTimes(1);
  await flush(1);
  expect(fetch).toHaveBeenCalledTimes(2);
  unmount();
  expect(vi.getTimerCount()).toBe(0);
});
it("read revision and terminal immutability reject stale higher-revision rewrites", async () => {
  vi.useFakeTimers();
  let revision = 2;
  const fetch = vi.fn(async () =>
    response({
      ...transcript,
      revision,
      calls: revision === 2 ? [savedCall] : [call],
    }),
  );
  vi.stubGlobal("fetch", fetch);
  const { result, unmount } = renderHook(() =>
    useToolTranscript(parseTurn(turn), true, 0),
  );
  await flush();
  revision = 3;
  await flush(500);
  expect(result.current.stale).toBe(true);
  expect(result.current.record?.calls[0].status).toBe("succeeded");
  unmount();
});
