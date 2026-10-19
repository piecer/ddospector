// Synthetic one-slot worker boundary; hook, component, client and wire parser are real.
import { StrictMode } from "react";
import {
  act,
  cleanup,
  fireEvent,
  render,
  renderHook,
  screen,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { PageProps } from "../../lib/contracts";
import { workspaceFixture } from "../../test/fixtures";
import { TargetsPage } from "../lab/targets";
import { inspection, target } from "./chat-target-test-fixtures";
import { response } from "./chat-test-fixtures";
import { useTargetReadback } from "./useTargetReadback";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

function props(): PageProps {
  return {
    data: workspaceFixture(),
    locale: "en",
    navigate: vi.fn(),
    refresh: vi.fn(),
    targetSelection: {
      id: target.id,
      expectation: { target: { ...target }, after_revision: 3 },
    },
  };
}

function worker(initiallyBusy = false) {
  // Aborting the HTTP consumer does NOT release admitted native work.
  // Only explicit settlement below releases its slot; excess requests get 429.
  let busy = initiallyBusy;
  let finish = () => {
    busy = false;
  };
  const events: string[] = [];
  const fetch = vi.fn((_url: RequestInfo | URL, init?: RequestInit) => {
    expect(_url).toBe("/api/v1/chat/tools/targets");
    expect(init?.method).toBe("GET");
    if (busy) {
      events.push("429");
      return Promise.resolve(
        response({ code: "CHAT_BUSY", message: "Worker busy" }, 429),
      );
    }
    busy = true;
    events.push("admit");
    return new Promise<Response>((resolve, reject) => {
      const abort = () => {
        events.push("abort-consumer");
        reject(new DOMException("Aborted", "AbortError"));
      };
      init?.signal?.addEventListener("abort", abort, { once: true });
      finish = () => {
        init?.signal?.removeEventListener("abort", abort);
        busy = false;
        events.push("settle");
        resolve(response(inspection));
      };
    });
  });
  vi.stubGlobal("fetch", fetch);
  return { fetch, events, settle: () => finish() };
}

it.each([false, true])(
  "actual TargetsPage with StrictMode=%s dispatches one live GET, not a retired effect",
  async (strict) => {
    const boundary = worker();
    const p = props();
    const page = <TargetsPage {...p} />;
    render(strict ? <StrictMode>{page}</StrictMode> : page);
    await act(async () => {});
    await act(async () => boundary.settle());
    expect(boundary.events).toEqual(["admit", "settle"]);
    expect(boundary.fetch).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("target-readback-status")).toHaveAttribute(
      "data-readback",
      "receipt-confirmed",
    );
    expect(screen.getByTestId(`target-row-${target.id}`)).toHaveFocus();
  },
);

it("ordinary unselected inventory under StrictMode sends zero GETs", async () => {
  const boundary = worker();
  render(
    <StrictMode>
      <TargetsPage {...props()} targetSelection={undefined} />
    </StrictMode>,
  );
  await act(async () => {});
  expect(boundary.fetch).not.toHaveBeenCalled();
});

it.each(["cancel", "unmount"])(
  "%s before dispatch sends zero GETs",
  async (action) => {
    const boundary = worker();
    const p = props();
    const { result, unmount } = renderHook(() =>
      useTargetReadback(p.targetSelection, p.data),
    );
    if (action === "cancel") act(() => result.current.cancel());
    else unmount();
    await act(async () => {});
    expect(boundary.fetch).not.toHaveBeenCalled();
    if (action === "cancel") {
      expect(result.current.state).toBe("unavailable");
      expect(result.current.pending).toBe(false);
    }
  },
);

it.each(["workspace", "selection"])(
  "%s supersession before dispatch retires only the old intent",
  async (change) => {
    const boundary = worker();
    const p = props();
    const { rerender } = render(<TargetsPage {...p} />);
    rerender(
      <TargetsPage
        {...p}
        data={change === "workspace" ? { ...p.data } : p.data}
        targetSelection={
          change === "selection" ? { id: target.id } : p.targetSelection
        }
      />,
    );
    await act(async () => {});
    await act(async () => boundary.settle());
    expect(boundary.events).toEqual(["admit", "settle"]);
    expect(screen.getByTestId("target-readback-status")).toHaveAttribute(
      "data-readback",
      change === "workspace" ? "receipt-confirmed" : "current-only",
    );
  },
);

it("genuine busy stays unavailable after the worker settles; only explicit retry issues another GET", async () => {
  const boundary = worker(true);
  render(
    <StrictMode>
      <TargetsPage {...props()} />
    </StrictMode>,
  );
  await act(async () => {});
  expect(screen.getByTestId("target-readback-status")).toHaveAttribute(
    "data-readback",
    "unavailable",
  );
  boundary.settle();
  vi.useFakeTimers();
  await act(async () => {
    await vi.advanceTimersByTimeAsync(60000);
  });
  vi.useRealTimers();
  expect(boundary.fetch).toHaveBeenCalledTimes(1);
  expect(screen.getByTestId("target-readback-status")).toHaveAttribute(
    "data-readback",
    "unavailable",
  );
  fireEvent.click(
    screen.getByRole("button", {
      name: "Read selected target again (GET only)",
    }),
  );
  await act(async () => {});
  await act(async () => boundary.settle());
  expect(boundary.fetch).toHaveBeenCalledTimes(2);
  expect(screen.getByTestId("target-readback-status")).toHaveAttribute(
    "data-readback",
    "receipt-confirmed",
  );
});

function lateResponses() {
  const requests: {
    signal: AbortSignal;
    resolve: (value: Response) => void;
  }[] = [];
  const fetch = vi.fn((_url: RequestInfo | URL, init?: RequestInit) => {
    expect(_url).toBe("/api/v1/chat/tools/targets");
    expect(init?.method).toBe("GET");
    // Model a response already in flight that wins its race with consumer abort.
    return new Promise<Response>((resolve) =>
      requests.push({ signal: init!.signal!, resolve }),
    );
  });
  vi.stubGlobal("fetch", fetch);
  return { requests, fetch };
}

it.each(["cancel", "unmount"])(
  "%s after dispatch aborts ownership and late success cannot confirm",
  async (action) => {
    const { requests, fetch } = lateResponses();
    const p = props();
    const { result, unmount } = renderHook(() =>
      useTargetReadback(p.targetSelection, p.data),
    );
    await act(async () => {});
    expect(requests).toHaveLength(1);
    if (action === "cancel") act(() => result.current.cancel());
    else unmount();
    expect(requests[0].signal.aborted).toBe(true);
    await act(async () => requests[0].resolve(response(inspection)));
    expect(fetch).toHaveBeenCalledTimes(1);
    if (action === "cancel") {
      expect(result.current.state).toBe("unavailable");
      expect(result.current.pending).toBe(false);
      expect(result.current.target).toBeUndefined();
    }
  },
);

it.each(["workspace", "selection"])(
  "late old %s response cannot confirm or settle its successor",
  async (change) => {
    const { requests } = lateResponses();
    const p = props();
    const { result, rerender } = renderHook(
      ({ data, targetSelection }: PageProps) =>
        useTargetReadback(targetSelection, data),
      { initialProps: p },
    );
    await act(async () => {});
    rerender({
      ...p,
      data: change === "workspace" ? { ...p.data } : p.data,
      targetSelection:
        change === "selection" ? { id: "next-target" } : p.targetSelection,
    });
    await act(async () => {});
    expect(requests).toHaveLength(2);
    expect(requests[0].signal.aborted).toBe(true);
    await act(async () => requests[0].resolve(response(inspection)));
    expect(result.current.pending).toBe(true);
    expect(result.current.state).toBe("loading");
    expect(result.current.target).toBeUndefined();
    const next =
      change === "workspace"
        ? { ...target, address: "changed.test" }
        : { ...target, id: "next-target" };
    await act(async () =>
      requests[1].resolve(response({ ...inspection, targets: [next] })),
    );
    expect(result.current.pending).toBe(false);
    expect(result.current.state).toBe(
      change === "workspace" ? "mismatch" : "current-only",
    );
    expect(result.current.target).toEqual(next);
  },
);

it("an in-flight native owner still refuses a superseding workspace GET without queuing or retry", async () => {
  const boundary = worker();
  const p = props();
  const { rerender } = render(<TargetsPage {...p} />);
  await act(async () => {});
  rerender(<TargetsPage {...p} data={{ ...p.data }} />);
  await act(async () => {});
  await act(async () => boundary.settle());
  expect(boundary.events).toEqual(["admit", "abort-consumer", "429", "settle"]);
  expect(boundary.fetch).toHaveBeenCalledTimes(2);
  expect(screen.getByTestId("target-readback-status")).toHaveAttribute(
    "data-readback",
    "unavailable",
  );
});

it("captures the handoff before dispatch rather than comparing a mutated alias", async () => {
  const { requests } = lateResponses();
  const p = props();
  render(<TargetsPage {...p} />);
  p.targetSelection!.expectation!.target.address = "altered.test";
  await act(async () => {});
  await act(async () =>
    requests[0].resolve(
      response({
        ...inspection,
        targets: [{ ...target, address: "altered.test" }],
      }),
    ),
  );
  expect(screen.getByTestId("target-readback-status")).toHaveAttribute(
    "data-readback",
    "mismatch",
  );
});

it("wire-invalid duplicate IDs remain unavailable, never receipt-confirmed", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => response({ ...inspection, targets: [target, target] })),
  );
  render(
    <StrictMode>
      <TargetsPage {...props()} />
    </StrictMode>,
  );
  await act(async () => {});
  expect(screen.getByTestId("target-readback-status")).toHaveAttribute(
    "data-readback",
    "unavailable",
  );
  expect(
    screen.queryByTestId(`target-row-${target.id}`),
  ).not.toBeInTheDocument();
});
