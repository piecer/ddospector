import { afterEach, expect, it, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { useToolAuthority } from "./useToolAuthority";
import { response } from "./chat-test-fixtures";
import { fence, cid, toolRuntime } from "./chat-tool-test-fixtures";
afterEach(() => vi.unstubAllGlobals());
it("a write fence does not prevent consented reads; workspace unavailability still blocks grants and writes", async () => {
  const fetch = vi.fn(async (url: string) =>
    response(
      url.endsWith("/runtime")
        ? toolRuntime
        : { ...fence, generation: 1, fenced: true, call_ids: [cid] },
    ),
  );
  vi.stubGlobal("fetch", fetch);
  const { result, rerender } = renderHook(
    ({ enabled }) => useToolAuthority(enabled),
    { initialProps: { enabled: true } },
  );
  expect(fetch).not.toHaveBeenCalled();
  await act(async () => {
    await result.current.refresh();
  });
  expect((result.current as unknown as { canGrant: boolean }).canGrant).toBe(
    true,
  );
  expect(result.current.canWrite).toBe(false);
  rerender({ enabled: false });
  expect((result.current as unknown as { canGrant: boolean }).canGrant).toBe(
    false,
  );
  expect(result.current.canWrite).toBe(false);
  await act(async () => {
    await result.current.refresh();
  });
  expect(fetch).toHaveBeenCalledTimes(4);
});
it("a fresh fence GET failure leaves authority unavailable without discarding the known fence", async () => {
  let failed = false;
  const fetch = vi.fn(async (url: string) => {
    if (failed) throw Error("offline");
    return response(url.endsWith("/runtime") ? toolRuntime : fence);
  });
  vi.stubGlobal("fetch", fetch);
  const { result } = renderHook(() => useToolAuthority(true));
  await act(async () => {
    await result.current.refresh();
  });
  expect(result.current.canWrite).toBe(true);
  failed = true;
  await act(async () => {
    await result.current.refresh();
  });
  expect(result.current.canWrite).toBe(false);
  expect(result.current.fence).toEqual(fence);
});
