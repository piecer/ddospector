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
import { SkillsPage } from "./SkillsPage";
import {
  skillInspection as inspection,
  draft as skill,
} from "./chat-skill-test-fixtures";
import { response } from "./chat-test-fixtures";
import { useSkillReadback } from "./useSkillReadback";

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
    skillSelection: {
      id: skill.id,
      expectation: {
        skill: JSON.parse(JSON.stringify(skill)),
        after_revision: 3,
      },
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
    expect(String(_url)).toMatch(
      /^\/api\/v1\/chat\/tools\/skills\/[a-z0-9-]+$/,
    );
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
  "actual SkillsPage with StrictMode=%s dispatches one live GET, not a retired effect",
  async (strict) => {
    const boundary = worker();
    const p = props();
    const page = <SkillsPage {...p} />;
    render(strict ? <StrictMode>{page}</StrictMode> : page);
    await act(async () => {});
    await act(async () => boundary.settle());
    expect(boundary.events).toEqual(["admit", "settle"]);
    expect(boundary.fetch).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("skill-readback-status")).toHaveAttribute(
      "data-readback",
      "receipt-confirmed",
    );
    expect(screen.getByRole("dialog")).toHaveAttribute("open");
  },
);

it("ordinary unselected inventory under StrictMode sends zero GETs", async () => {
  const boundary = worker();
  render(
    <StrictMode>
      <SkillsPage {...props()} skillSelection={undefined} />
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
      useSkillReadback(p.skillSelection, p.data),
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
    const { rerender } = render(<SkillsPage {...p} />);
    rerender(
      <SkillsPage
        {...p}
        data={change === "workspace" ? { ...p.data } : p.data}
        skillSelection={
          change === "selection" ? { id: skill.id } : p.skillSelection
        }
      />,
    );
    await act(async () => {});
    await act(async () => boundary.settle());
    expect(boundary.events).toEqual(["admit", "settle"]);
    expect(screen.getByTestId("skill-readback-status")).toHaveAttribute(
      "data-readback",
      change === "workspace" ? "receipt-confirmed" : "current-only",
    );
  },
);

it("genuine busy stays unavailable after the worker settles; only explicit retry issues another GET", async () => {
  const boundary = worker(true);
  render(
    <StrictMode>
      <SkillsPage {...props()} />
    </StrictMode>,
  );
  await act(async () => {});
  expect(screen.getByTestId("skill-readback-status")).toHaveAttribute(
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
  expect(screen.getByTestId("skill-readback-status")).toHaveAttribute(
    "data-readback",
    "unavailable",
  );
  fireEvent.click(
    screen.getByRole("button", {
      name: "Read selected Skill again (GET only)",
    }),
  );
  await act(async () => {});
  await act(async () => boundary.settle());
  expect(boundary.fetch).toHaveBeenCalledTimes(2);
  expect(screen.getByTestId("skill-readback-status")).toHaveAttribute(
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
    expect(String(_url)).toMatch(
      /^\/api\/v1\/chat\/tools\/skills\/[a-z0-9-]+$/,
    );
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
      useSkillReadback(p.skillSelection, p.data),
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
      expect(result.current.skill).toBeUndefined();
    }
  },
);

it.each(["workspace", "selection"])(
  "late old %s response cannot confirm or settle its successor",
  async (change) => {
    const { requests } = lateResponses();
    const p = props();
    const { result, rerender } = renderHook(
      ({ data, skillSelection }: PageProps) =>
        useSkillReadback(skillSelection, data),
      { initialProps: p },
    );
    await act(async () => {});
    rerender({
      ...p,
      data: change === "workspace" ? { ...p.data } : p.data,
      skillSelection:
        change === "selection" ? { id: "next-skill" } : p.skillSelection,
    });
    await act(async () => {});
    expect(requests).toHaveLength(2);
    expect(requests[0].signal.aborted).toBe(true);
    await act(async () => requests[0].resolve(response(inspection)));
    expect(result.current.pending).toBe(true);
    expect(result.current.state).toBe("loading");
    expect(result.current.skill).toBeUndefined();
    const next =
      change === "workspace"
        ? { ...skill, instructions: { en: "changed", ko: "changed" } }
        : { ...skill, id: "next-skill" };
    await act(async () =>
      requests[1].resolve(response({ ...inspection, skill: next })),
    );
    expect(result.current.pending).toBe(false);
    expect(result.current.state).toBe(
      change === "workspace" ? "discrepancy" : "current-only",
    );
    expect(result.current.skill).toEqual(next);
  },
);

it("an in-flight native owner still refuses a superseding workspace GET without queuing or retry", async () => {
  const boundary = worker();
  const p = props();
  const { rerender } = render(<SkillsPage {...p} />);
  await act(async () => {});
  rerender(<SkillsPage {...p} data={{ ...p.data }} />);
  await act(async () => {});
  await act(async () => boundary.settle());
  expect(boundary.events).toEqual(["admit", "abort-consumer", "429", "settle"]);
  expect(boundary.fetch).toHaveBeenCalledTimes(2);
  expect(screen.getByTestId("skill-readback-status")).toHaveAttribute(
    "data-readback",
    "unavailable",
  );
});

it("captures the handoff before dispatch rather than comparing a mutated alias", async () => {
  const { requests } = lateResponses();
  const p = props();
  render(<SkillsPage {...p} />);
  p.skillSelection!.expectation!.skill.instructions.en = "altered";
  await act(async () => {});
  await act(async () =>
    requests[0].resolve(
      response({
        ...inspection,
        skill: { ...skill, instructions: { en: "altered", ko: "altered" } },
      }),
    ),
  );
  expect(screen.getByTestId("skill-readback-status")).toHaveAttribute(
    "data-readback",
    "discrepancy",
  );
});

it("wire-invalid detail remains unavailable, never receipt-confirmed", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () =>
      response({ ...inspection, skill: { ...skill, created_at: "invented" } }),
    ),
  );
  render(
    <StrictMode>
      <SkillsPage {...props()} />
    </StrictMode>,
  );
  await act(async () => {});
  expect(screen.getByTestId("skill-readback-status")).toHaveAttribute(
    "data-readback",
    "unavailable",
  );
  expect(document.querySelector(".ai-skill-details")).toBeNull();
});
