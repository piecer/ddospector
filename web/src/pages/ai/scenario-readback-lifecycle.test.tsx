import { afterEach, expect, it, vi } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import { useScenarioReadback } from "./useScenarioReadback";
import { recordFixture } from "../scenarios/testRecords";
import { response } from "./chat-test-fixtures";
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
it.each([
  "exact",
  "wrong",
  "below",
  "missing",
  "unavailable",
  "corrupt-unselected",
] as const)("exact older full record readback: %s", async (kind) => {
  const first = await recordFixture(1, { id: "legacy-scenario" }),
    second = await recordFixture(2, { id: first.id });
  const history = {
    revision: 2,
    scenario_id: first.id,
    versions: kind === "missing" ? [first] : [first, second],
    execution_enabled: false,
  };
  const selection = {
    id: first.id,
    version: kind === "missing" ? 2 : 1,
    expectation: {
      scenario: kind === "missing" ? second : structuredClone(first),
      after_scenario_revision: kind === "below" ? 3 : 1,
    },
  };
  if (kind === "wrong")
    history.versions[0] = await recordFixture(1, {
      id: first.id,
      definition: { ...first.definition, name: "different" },
    });
  if (kind === "corrupt-unselected")
    history.versions[1].digest = "0".repeat(64);
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => {
      if (kind === "unavailable") throw Error("outage");
      return response(history);
    }),
  );
  const { result } = renderHook(() => useScenarioReadback(selection));
  await waitFor(() =>
    expect(result.current.state).toBe(
      kind === "exact"
        ? "receipt-confirmed"
        : kind === "unavailable" || kind === "corrupt-unselected"
          ? "unavailable"
          : "discrepancy",
    ),
  );
});
it("replacing selection retains a single read owner until an aborted late fetch retires", async () => {
  const first = await recordFixture(1, { id: "legacy-scenario" }),
    second = await recordFixture(2, { id: first.id });
  const body = {
    revision: 2,
    scenario_id: first.id,
    versions: [first, second],
    execution_enabled: false,
  };
  let release!: (r: Response) => void;
  const fetcher = vi
    .fn()
    .mockImplementationOnce(
      () =>
        new Promise<Response>((r) => {
          release = r;
        }),
    )
    .mockImplementation(async () => response(body));
  vi.stubGlobal("fetch", fetcher);
  const { result, rerender } = renderHook(
    ({ selection }) => useScenarioReadback(selection),
    {
      initialProps: {
        selection: { id: first.id, version: 1, expectation: null },
      },
    },
  );
  await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
  rerender({ selection: { id: first.id, version: 2, expectation: null } });
  await act(async () => {
    await new Promise((r) => setTimeout(r, 20));
  });
  expect(fetcher).toHaveBeenCalledTimes(1);
  await act(async () => release(response(body)));
  await waitFor(() => expect(result.current.record?.version).toBe(2));
  expect(fetcher).toHaveBeenCalledTimes(2);
});

it("Cancel retires publication and locale-only rerender neither retries nor reopens a late response", async () => {
  const record = await recordFixture(),
    selection = { id: record.id, version: 1, expectation: null };
  let release!: (r: Response) => void;
  const fetcher = vi.fn(
    () =>
      new Promise<Response>((r) => {
        release = r;
      }),
  );
  vi.stubGlobal("fetch", fetcher);
  const { result, rerender } = renderHook(
    ({ locale }) => {
      void locale;
      return useScenarioReadback(selection);
    },
    { initialProps: { locale: "en" } },
  );
  await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
  act(() => result.current.cancel());
  rerender({ locale: "ko" });
  await act(async () =>
    release(
      response({
        revision: 1,
        scenario_id: record.id,
        versions: [record],
        execution_enabled: false,
      }),
    ),
  );
  expect(result.current.state).toBe("cancelled");
  expect(result.current.record).toBeNull();
  expect(fetcher).toHaveBeenCalledTimes(1);
});

import type { ScenarioSelection } from "./chat-scenario-types";
it("RB01 manual logical abort retains original 10000ms U0 deadline before selected acquisition", async () => {
  const record = await recordFixture();
  const body = {
    revision: 1,
    scenario_id: record.id,
    versions: [record],
    execution_enabled: false,
  };
  vi.useFakeTimers();
  try {
    let transport!: AbortSignal;
    const schedule: string[] = [];
    const fetcher = vi.fn((url: string, init?: RequestInit) => {
      expect(url).toBe("/api/v1/scenarios/" + record.id);
      if (!transport) {
        transport = init!.signal!;
        schedule.push("manual:start");
        transport.addEventListener("abort", () =>
          schedule.push("manual:deadline"),
        );
        return new Promise<Response>(() => {}); // deliberately ignores abort
      }
      expect(transport.aborted).toBe(true);
      schedule.push("selected:start");
      return Promise.resolve(response(body));
    });
    vi.stubGlobal("fetch", fetcher);
    const { result, rerender, unmount } = renderHook(
      ({ selection }: { selection?: ScenarioSelection }) =>
        useScenarioReadback(selection),
      { initialProps: {} },
    );
    const controller = new AbortController();
    const manual = result.current.readManualHistory(
      record.id,
      controller.signal,
    );
    const cancelled = manual.catch((error) => error);
    expect(fetcher).toHaveBeenCalledTimes(1);
    controller.abort();
    await expect(cancelled).resolves.toMatchObject({ name: "AbortError" });
    rerender({
      selection: { id: record.id, version: 1, expectation: null },
    });
    act(() => {
      void result.current.retry();
      void result.current.retry();
    });
    await act(() => vi.advanceTimersByTimeAsync(9999));
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(transport.aborted).toBe(false);
    await act(() => vi.advanceTimersByTimeAsync(1));
    expect(schedule).toEqual([
      "manual:start",
      "manual:deadline",
      "selected:start",
    ]);
    vi.useRealTimers();
    await waitFor(() => expect(result.current.state).toBe("current-only"));
    expect(result.current.record).toEqual(record);
    expect(fetcher).toHaveBeenCalledTimes(2);
    unmount();
  } finally {
    vi.useRealTimers();
  }
});
it.each(["replace", "abort", "unmount"] as const)(
  "RB01 manual waiters settle without extra transports on %s",
  async (kind) => {
    const record = await recordFixture();
    const body = {
      revision: 1,
      scenario_id: record.id,
      versions: [record],
      execution_enabled: false,
    };
    let release!: (r: Response) => void;
    const fetcher = vi
      .fn()
      .mockImplementationOnce(
        () =>
          new Promise<Response>((r) => {
            release = r;
          }),
      )
      .mockImplementation(async () => response(body));
    vi.stubGlobal("fetch", fetcher);
    const { result, unmount } = renderHook(() => useScenarioReadback());
    const first = new AbortController(),
      second = new AbortController(),
      third = new AbortController();
    const active = result.current
      .readManualHistory(record.id, first.signal)
      .catch((error) => error);
    const waiting = result.current
      .readManualHistory(record.id, second.signal)
      .catch((error) => error);
    let latest: Promise<unknown> | undefined;
    if (kind === "replace")
      latest = result.current.readManualHistory(record.id, third.signal);
    else if (kind === "abort") second.abort();
    else unmount();
    await expect(waiting).resolves.toMatchObject({ name: "AbortError" });
    expect(fetcher).toHaveBeenCalledTimes(1);
    await act(async () => {
      release(response(body));
      await active;
      await latest;
    });
    expect(fetcher).toHaveBeenCalledTimes(kind === "replace" ? 2 : 1);
    if (latest) await expect(latest).resolves.toEqual(body);
    if (kind === "unmount")
      await expect(active).resolves.toMatchObject({ name: "AbortError" });
  },
);
it.each(["invalid-UUID", "fetch-rejection", "malformed-history"] as const)(
  "RB01 manual %s settles its caller and still permits a properly validated selected read",
  async (kind) => {
    const record = await recordFixture();
    const body = {
      revision: 1,
      scenario_id: record.id,
      versions: [record],
      execution_enabled: false,
    };
    const fetcher = vi.fn(async () => response(body));
    if (kind === "fetch-rejection")
      fetcher.mockRejectedValueOnce(Error("scripted read failure"));
    if (kind === "malformed-history")
      fetcher.mockResolvedValueOnce(
        response({
          ...body,
          versions: [{ ...record, digest: "0".repeat(64) }],
        }),
      );
    vi.stubGlobal("fetch", fetcher);
    const { result, rerender } = renderHook(
      ({ selection }: { selection?: ScenarioSelection }) =>
        useScenarioReadback(selection),
      { initialProps: {} },
    );
    const controller = new AbortController();
    await expect(
      result.current.readManualHistory(
        kind === "invalid-UUID" ? "legacy-scenario" : record.id,
        controller.signal,
      ),
    ).rejects.toBeDefined();
    rerender({
      selection: { id: record.id, version: 1, expectation: null },
    });
    await waitFor(() => expect(result.current.state).toBe("current-only"));
    expect(result.current.record).toEqual(record);
  },
);
