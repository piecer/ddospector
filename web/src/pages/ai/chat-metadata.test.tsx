import { StrictMode } from "react";
import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useChat } from "./useChat";
import { useToolAuthority } from "./useToolAuthority";
import { response, runtimeFixture } from "./chat-test-fixtures";
import { fence, toolRuntime } from "./chat-tool-test-fixtures";
import { chatJSON, ChatRequestError } from "./chat-client";

const busy = () =>
  response({ code: "CHAT_BUSY", message: "Chat is busy." }, 429);
const sessions = () => response({ schema_version: 1, sessions: [] });
const flush = () => act(async () => {});
const advance = (ms: number) =>
  act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
beforeEach(() => vi.useFakeTimers());
afterEach(() => {
  cleanup();
  expect(vi.getTimerCount()).toBe(0);
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

it("serializes tool runtime and fence native reads instead of adopting a contention-null revision", async () => {
  let release!: (value: Response) => void;
  let nativeBusy = false;
  const fetch = vi.fn(async (url: string) => {
    if (url.endsWith("/runtime")) {
      nativeBusy = true;
      return new Promise<Response>((resolve) => {
        release = resolve;
      });
    }
    return response({
      ...fence,
      current_draft_revision: nativeBusy ? null : fence.current_draft_revision,
    });
  });
  vi.stubGlobal("fetch", fetch);
  const { result } = renderHook(() => useToolAuthority(true));
  let pending!: Promise<void>;
  act(() => {
    pending = result.current.refresh();
  });
  await flush();
  expect(result.current.canGrant).toBe(false);
  await act(async () => {
    nativeBusy = false;
    release(response(toolRuntime));
    await pending;
  });
  expect(result.current.canGrant).toBe(true);
  expect(result.current.canWrite).toBe(true);
  expect(fetch).toHaveBeenCalledTimes(2);
});

it("retries only the busy metadata GET after completion, retaining edited input", async () => {
  let release!: (value: Response) => void;
  let attempts = 0;
  const fetch = vi.fn(async (url: string) => {
    if (url.endsWith("/sessions")) return sessions();
    if (++attempts === 1)
      return new Promise<Response>((resolve) => {
        release = resolve;
      });
    return response(runtimeFixture);
  });
  vi.stubGlobal("fetch", fetch);
  const { result } = renderHook(() => useChat("en", true));
  act(() => result.current.setInput("dirty draft"));
  await advance(800);
  expect(attempts).toBe(1);
  await act(async () => release(busy()));
  await advance(499);
  expect(attempts).toBe(1);
  expect(result.current.runtime).toBeNull();
  await advance(1);
  expect(attempts).toBe(2);
  expect(result.current.phase).toBe("ready");
  expect(result.current.input).toBe("dirty draft");
  expect(
    fetch.mock.calls.filter(([url]) => url.endsWith("/sessions")),
  ).toHaveLength(1);
});

it("exhausts three CHAT_BUSY attempts and leaves an explicit read error without more timers", async () => {
  const fetch = vi.fn(async (url: string) =>
    url.endsWith("/runtime") ? busy() : sessions(),
  );
  vi.stubGlobal("fetch", fetch);
  const { result } = renderHook(() => useChat("en", true));
  await flush();
  await advance(1000);
  expect(result.current.phase).toBe("read-error");
  expect(result.current.runtime).toBeNull();
  expect(
    fetch.mock.calls.filter(([url]) => url.endsWith("/runtime")),
  ).toHaveLength(3);
  expect(vi.getTimerCount()).toBe(0);
  await advance(10000);
  expect(fetch).toHaveBeenCalledTimes(4);
});

it.each(["network", "schema", "other-429", "storage"])(
  "does not retry %s failures",
  async (kind) => {
    const fetch = vi.fn(async (url: string) => {
      if (url.endsWith("/sessions")) return sessions();
      if (kind === "network") throw Error("offline");
      if (kind === "schema") return response({ invalid: true });
      return response(
        {
          code:
            kind === "storage" ? "CHAT_STORAGE_ERROR" : "CHAT_INVALID_REQUEST",
          message: "No",
        },
        kind === "storage" ? 503 : 429,
      );
    });
    vi.stubGlobal("fetch", fetch);
    const { result } = renderHook(() => useChat("en", true));
    await flush();
    expect(result.current.phase).toBe("read-error");
    await advance(10000);
    expect(fetch).toHaveBeenCalledTimes(2);
  },
);

it("a sibling nonbusy error cancels a pending busy retry", async () => {
  const fetch = vi.fn(async (url: string) => {
    if (url.endsWith("/runtime")) return busy();
    // Allow the runtime's parsed CHAT_BUSY to enter its wait first.
    await new Promise((resolve) => setTimeout(resolve, 10));
    throw Error("offline");
  });
  vi.stubGlobal("fetch", fetch);
  const { result } = renderHook(() => useChat("en", true));
  await flush();
  await advance(10);
  expect(result.current.phase).toBe("read-error");
  expect(vi.getTimerCount()).toBe(0);
  await advance(2000);
  expect(fetch).toHaveBeenCalledTimes(2);
});

it("StrictMode abort/restart and superseding refresh cannot adopt or retry the old owner", async () => {
  const signals: AbortSignal[] = [];
  let release!: (value: Response) => void;
  let calls = 0;
  const fetch = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith("/sessions")) return sessions();
    signals.push(init!.signal!);
    ++calls;
    if (calls === 1)
      return new Promise<Response>((resolve) => {
        release = resolve;
      });
    if (calls === 2) return busy();
    return response(runtimeFixture);
  });
  vi.stubGlobal("fetch", fetch);
  const { result, unmount } = renderHook(() => useChat("en", true), {
    wrapper: StrictMode,
  });
  await flush();
  expect(signals[0].aborted).toBe(true);
  await act(async () => {
    await result.current.refresh();
  });
  expect(result.current.runtime?.supported).toBe(true);
  await act(async () => release(busy()));
  await advance(2000);
  expect(calls).toBe(3);
  unmount();
  expect(signals.every((signal) => signal.aborted)).toBe(true);
});

it("unmount during a retry wait cancels the timer and never makes another GET", async () => {
  const fetch = vi.fn(async (url: string) =>
    url.endsWith("/runtime") ? busy() : sessions(),
  );
  vi.stubGlobal("fetch", fetch);
  const { unmount } = renderHook(() => useChat("en", true));
  await flush();
  expect(vi.getTimerCount()).toBe(1);
  unmount();
  await flush();
  expect(vi.getTimerCount()).toBe(0);
  await advance(2000);
  expect(fetch).toHaveBeenCalledTimes(2);
});

it("authority stays unavailable during busy retry and preserves the actual fence", async () => {
  let attempts = 0;
  const fetch = vi.fn(async (url: string) =>
    url.endsWith("/runtime")
      ? ++attempts === 1
        ? busy()
        : response(toolRuntime)
      : response({
          ...fence,
          fenced: true,
          generation: 1,
          call_ids: ["44444444-4444-4444-8444-444444444444"],
        }),
  );
  vi.stubGlobal("fetch", fetch);
  const { result } = renderHook(() => useToolAuthority(true));
  act(() => {
    void result.current.refresh();
  });
  await flush();
  expect(result.current.canGrant).toBe(false);
  expect(result.current.canWrite).toBe(false);
  await advance(500);
  expect(result.current.canGrant).toBe(true);
  expect(result.current.canWrite).toBe(false);
  expect(attempts).toBe(2);
});

it.each(["CHAT_BUSY", "CHAT_STORAGE_ERROR"])(
  "authority %s failure stays closed with finite reads",
  async (code) => {
    const fetch = vi.fn(async () =>
      response({ code, message: "No" }, code === "CHAT_BUSY" ? 429 : 503),
    );
    vi.stubGlobal("fetch", fetch);
    const { result } = renderHook(() => useToolAuthority(true));
    act(() => {
      void result.current.refresh();
    });
    await flush();
    await advance(10000);
    expect(fetch).toHaveBeenCalledTimes(code === "CHAT_BUSY" ? 3 : 1);
    expect(result.current.ready).toBe(false);
    expect(result.current.canGrant).toBe(false);
    expect(result.current.canWrite).toBe(false);
  },
);

it("authority ignores a late successful fence from a superseded refresh", async () => {
  let release!: (value: Response) => void;
  let reads = 0;
  const fetch = vi.fn(async (url: string) => {
    if (url.endsWith("/runtime")) return response(toolRuntime);
    if (++reads === 1)
      return new Promise<Response>((resolve) => {
        release = resolve;
      });
    return response({ ...fence, current_draft_revision: 1 });
  });
  vi.stubGlobal("fetch", fetch);
  const { result } = renderHook(() => useToolAuthority(true));
  let old!: Promise<void>;
  act(() => {
    old = result.current.refresh();
  });
  await flush();
  await act(async () => {
    await result.current.refresh();
  });
  expect(result.current.fence?.current_draft_revision).toBe(1);
  await act(async () => {
    release(response(fence));
    await old;
  });
  expect(result.current.fence?.current_draft_revision).toBe(1);
  expect(result.current.canGrant).toBe(true);
});

it.each([
  "/sessions",
  "/tool-grants",
  "/sessions/id/tool-turns",
  "/tool-calls/id/decision",
  "/tools/reconcile",
  "/turns/id/cancel",
])("never retries CHAT_BUSY POST %s", async (path) => {
  const fetch = vi.fn(async () => busy());
  vi.stubGlobal("fetch", fetch);
  await expect(chatJSON(path, "POST", {})).rejects.toBeInstanceOf(
    ChatRequestError,
  );
  await advance(10000);
  expect(fetch).toHaveBeenCalledTimes(1);
});

it("authority unmount and superseding inspect cancel pending refresh retries", async () => {
  const fetch = vi.fn(async () => busy());
  vi.stubGlobal("fetch", fetch);
  const { result, unmount } = renderHook(() => useToolAuthority(true));
  act(() => {
    void result.current.refresh();
  });
  await flush();
  expect(vi.getTimerCount()).toBe(1);
  await act(async () => {
    await result.current.inspect();
  });
  expect(result.current.reviewState).toBe("unknown");
  expect(result.current.canGrant).toBe(false);
  expect(vi.getTimerCount()).toBe(0);
  act(() => {
    void result.current.refresh();
  });
  await flush();
  expect(vi.getTimerCount()).toBe(1);
  unmount();
  await flush();
  expect(vi.getTimerCount()).toBe(0);
  const calls = fetch.mock.calls.length;
  await advance(2000);
  expect(fetch).toHaveBeenCalledTimes(calls);
});
