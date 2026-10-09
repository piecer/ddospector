import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "./api";
afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});
describe("API errors and draft request contract", () => {
  it("rejects a failed response instead of presenting it as saved", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          new Response(
            JSON.stringify({
              code: "CAPACITY_EXCEEDED",
              message: "Draft limit reached",
            }),
            { status: 429, headers: { "Content-Type": "application/json" } },
          ),
        ),
    );
    await expect(
      api.createTarget({ name: "Lab", address: "192.0.2.10", kind: "DUT" }),
    ).rejects.toThrow("Draft limit reached");
  });
  it("submits a JSON draft, not a network connection request", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify({ id: "target-1" }), { status: 201 }),
      );
    vi.stubGlobal("fetch", fetchMock);
    await api.createTarget({ name: "Lab", address: "192.0.2.10", kind: "DUT" });
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/targets",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          name: "Lab",
          address: "192.0.2.10",
          kind: "DUT",
        }),
      }),
    );
  });
  it("bounds a stalled workspace read so startup can offer retry", async () => {
    vi.useFakeTimers();
    vi.stubGlobal(
      "fetch",
      vi.fn(
        (_url: string, options: RequestInit) =>
          new Promise((_resolve, reject) => {
            options.signal?.addEventListener(
              "abort",
              () => reject(options.signal?.reason),
              { once: true },
            );
          }),
      ),
    );
    let settled = false;
    const request = api.getWorkspace().catch(() => {
      settled = true;
    });
    await vi.advanceTimersByTimeAsync(10_001);
    expect(settled).toBe(true);
    await request;
    expect(vi.getTimerCount()).toBe(0);
  });
});
