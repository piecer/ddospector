import { afterEach, expect, it, vi } from "vitest";
import { aiSettingsAPI } from "./client";
import type { AISettingsInput } from "./types";
import { deferred, empty, profile, response } from "./testFixtures";
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  vi.useRealTimers();
});

it.each([
  { ...empty(), execution_enabled: true },
  { ...empty(), connection_status: "healthy" },
  { ...empty(), revision: Number.MAX_SAFE_INTEGER + 1 },
  { ...empty(), revision: -1 },
  { ...empty(), revision: true },
  { ...empty(), enabled: false },
  { ...empty(), updated_at: "2026-10-09T12:00:00" },
  {
    ...empty(),
    profiles: [
      profile({
        format: "anthropic",
        max_tokens_field: "max_completion_tokens",
      }),
    ],
  },
  { ...empty(), profiles: [{ ...profile(), api_key: "NEVER_RENDER" }] },
  {
    ...empty(),
    profiles: [{ ...profile(), retry: { ...profile().retry, future: {} } }],
  },
  {
    ...empty(),
    profiles: [profile({ streaming: "false" as unknown as boolean })],
  },
  { ...empty(), profiles: [profile(), profile()] },
  {
    ...empty(),
    profiles: [profile({ name: "Σ" }), profile({ id: "llm-other", name: "ς" })],
  },
  { ...empty(), default_profile_id: "missing" },
  { ...empty(), agent_profile_id: "missing" },
  { revision: 0, profiles: [] },
])("rejects an invalid closed snapshot %#", async (value) => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(value)));
  await expect(aiSettingsAPI.read()).rejects.toThrow();
});

it("does not persist or redirect settings requests", async () => {
  const fetcher = vi.fn().mockResolvedValue(response(empty()));
  vi.stubGlobal("fetch", fetcher);
  await aiSettingsAPI.read();
  expect(fetcher).toHaveBeenCalledWith(
    "/api/v1/ai-settings",
    expect.objectContaining({
      cache: "no-store",
      redirect: "error",
      credentials: "same-origin",
    }),
  );
});

it("rejects an invalid replacement before any network call", async () => {
  const fetcher = vi.fn();
  vi.stubGlobal("fetch", fetcher);
  await expect(
    aiSettingsAPI.save({
      revision: 0,
      profiles: [profile({ max_tokens: Infinity })],
      default_profile_id: null,
      agent_profile_id: null,
    }),
  ).rejects.toThrow();
  await expect(
    aiSettingsAPI.save({
      revision: Number.MAX_SAFE_INTEGER,
      profiles: [],
      default_profile_id: null,
      agent_profile_id: null,
    }),
  ).rejects.toThrow();
  await expect(
    aiSettingsAPI.save({
      ...empty(),
      api_key: "not allowed",
    } as unknown as AISettingsInput),
  ).rejects.toThrow();
  expect(fetcher).not.toHaveBeenCalled();
});

it("cancels an over-budget response body without parsing it", async () => {
  const cancel = vi.fn();
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(
        new ReadableStream({
          start(c) {
            c.enqueue(new Uint8Array(262145));
          },
          cancel,
        }),
        { headers: { "Content-Type": "application/json" } },
      ),
    ),
  );
  vi.useFakeTimers();
  const result = aiSettingsAPI.read().catch((error) => error);
  await vi.advanceTimersByTimeAsync(0);
  expect(cancel).toHaveBeenCalledOnce();
  expect(await result).toBeInstanceOf(Error);
  expect(vi.getTimerCount()).toBe(0);
});

it("cancels a late body when fetch settles after caller abort", async () => {
  const held = deferred<Response>();
  vi.stubGlobal("fetch", vi.fn().mockReturnValue(held.promise));
  const controller = new AbortController();
  const result = aiSettingsAPI.read(controller.signal).catch((error) => error);
  controller.abort();
  await result;
  const cancel = vi.fn();
  held.resolve(new Response(new ReadableStream({ cancel })));
  await new Promise((resolve) => setTimeout(resolve, 0));
  expect(cancel).toHaveBeenCalledOnce();
});

it("bounds body acquisition with the same deadline and releases its reader", async () => {
  vi.useFakeTimers();
  const cancel = vi.fn();
  const body = new ReadableStream({ cancel });
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(body)));
  const result = aiSettingsAPI.read().catch((error) => error);
  await vi.advanceTimersByTimeAsync(10_000);
  expect((await result).name).toBe("TimeoutError");
  expect(cancel).toHaveBeenCalledOnce();
  expect(body.locked).toBe(false);
  expect(vi.getTimerCount()).toBe(0);
});

it("cleans timeout timers and external listeners on successful reads and caller abort", async () => {
  vi.useFakeTimers();
  const controller = new AbortController();
  const add = vi.spyOn(controller.signal, "addEventListener");
  const remove = vi.spyOn(controller.signal, "removeEventListener");
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValueOnce(response(empty()))
      .mockImplementationOnce(() => new Promise(() => {})),
  );
  await expect(aiSettingsAPI.read(controller.signal)).resolves.toEqual(empty());
  expect(remove).toHaveBeenCalledWith("abort", add.mock.calls[0][1]);
  expect(vi.getTimerCount()).toBe(0);
  const result = aiSettingsAPI.read(controller.signal).catch((error) => error);
  controller.abort();
  expect((await result).name).toBe("AbortError");
  expect(vi.getTimerCount()).toBe(0);
  expect(remove).toHaveBeenCalledTimes(2);
});
