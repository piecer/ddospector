import type { ComponentType } from "react";
import { afterEach, expect, it, vi } from "vitest";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { Application } from "./App";
import { api } from "./lib/api";
import { navigation, type RouteId } from "./lib/navigation";
import type { PageProps } from "./lib/contracts";
import { ProfilesPage } from "./pages/lab/profiles";
import { recordFixture } from "./pages/scenarios/testRecords";
import { response } from "./pages/ai/chat-test-fixtures";
const pages = Object.fromEntries(
  navigation.map((n) => [n.id, ProfilesPage]),
) as Record<RouteId, ComponentType<PageProps>>;
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
it("cold exact Identifier/version inspection is read-only and usable without workspace", async () => {
  localStorage.setItem("aegis.locale", "en");
  window.history.replaceState(
    null,
    "",
    "/profiles?scenario=legacy-scenario&version=1",
  );
  vi.spyOn(api, "getWorkspace").mockRejectedValue(Error("outage"));
  const first = await recordFixture(1, { id: "legacy-scenario" }),
    second = await recordFixture(2, { id: first.id });
  const fetcher = vi.fn(async () =>
    response({
      revision: 2,
      scenario_id: first.id,
      versions: [first, second],
      execution_enabled: false,
    }),
  );
  vi.stubGlobal("fetch", fetcher);
  render(<Application pages={pages} />);
  await waitFor(() =>
    expect(screen.getByTestId("scenario-readback-status")).toHaveAttribute(
      "data-readback",
      "current-only",
    ),
  );
  expect(screen.getByText(first.digest)).toBeInTheDocument();
  expect(screen.queryByText(second.digest)).toBeNull();
  expect(
    screen.getByRole("button", {
      name: "Read selected scenario again (GET only)",
    }),
  ).toBeEnabled();
  expect(fetcher).toHaveBeenCalledTimes(1);
  fireEvent.click(
    screen.getByRole("button", { name: "Cancel scenario inspection" }),
  );
  expect(screen.queryByText(first.digest)).toBeNull();
  act(() => {
    window.history.replaceState(
      null,
      "",
      "/profiles?scenario=legacy-scenario&version=2",
    );
    window.dispatchEvent(new PopStateEvent("popstate"));
  });
  await waitFor(() =>
    expect(screen.getByText(second.digest)).toBeInTheDocument(),
  );
  expect(fetcher).toHaveBeenCalledTimes(2);
});

import { workspaceFixture } from "./test/fixtures";
import type { ScenarioExpectation } from "./pages/ai/chat-scenario-types";
it("App freezes full Saved expectation before async validation, navigates exact older version and drops authority on popstate", async () => {
  localStorage.setItem("aegis.locale", "en");
  window.history.replaceState(null, "", "/overview");
  vi.spyOn(api, "getWorkspace").mockResolvedValue(workspaceFixture());
  const first = await recordFixture(1, { id: "legacy-scenario" }),
    second = await recordFixture(2, { id: first.id });
  const expectation: ScenarioExpectation = {
    scenario: structuredClone(first),
    after_scenario_revision: 1,
  };
  const fetcher = vi.fn(async (u: string) =>
    response(
      u.includes("?")
        ? {
            revision: 2,
            total: 1,
            offset: 0,
            limit: 50,
            items: [second],
            execution_enabled: false,
          }
        : {
            revision: 2,
            scenario_id: first.id,
            versions: [first, second],
            execution_enabled: false,
          },
    ),
  );
  vi.stubGlobal("fetch", fetcher);
  function Handoff({ navigate }: PageProps) {
    return (
      <button
        onClick={() => {
          navigate("profiles", { id: first.id, version: 1, expectation });
          expectation.scenario.definition.name = "mutated";
          expectation.after_scenario_revision = 999;
        }}
      >
        Saved link seam
      </button>
    );
  }
  render(<Application pages={{ ...pages, overview: Handoff }} />);
  fireEvent.click(
    await screen.findByRole("button", { name: "Saved link seam" }),
  );
  await waitFor(() =>
    expect(window.location.pathname + window.location.search).toBe(
      "/profiles?scenario=legacy-scenario&version=1",
    ),
  );
  expect(window.history.state).toBeNull();
  await waitFor(() =>
    expect(screen.getByTestId("scenario-readback-status")).toHaveAttribute(
      "data-readback",
      "receipt-confirmed",
    ),
  );
  expect(
    fetcher.mock.calls.filter(
      ([u]) => u === "/api/v1/scenarios/legacy-scenario",
    ),
  ).toHaveLength(1);
  act(() =>
    window.dispatchEvent(
      new PopStateEvent("popstate", { state: { expectation } }),
    ),
  );
  await waitFor(() =>
    expect(screen.getByTestId("scenario-readback-status")).toHaveAttribute(
      "data-readback",
      "current-only",
    ),
  );
});

import userEvent from "@testing-library/user-event";
it("selected readback shares history with the real library and preserves dirty manual editor through locale/outage", async () => {
  window.history.replaceState(null, "", "/profiles");
  localStorage.setItem("aegis.locale", "en");
  const record = await recordFixture(),
    data = workspaceFixture();
  data.targets = [record.target_snapshot, record.sink_snapshot];
  vi.spyOn(api, "getWorkspace").mockResolvedValue(data);
  const fetcher = vi.fn(async (u: string) =>
    response(
      u.includes("?")
        ? {
            revision: 1,
            total: 1,
            offset: 0,
            limit: 50,
            items: [record],
            execution_enabled: false,
          }
        : {
            revision: 1,
            scenario_id: record.id,
            versions: [record],
            execution_enabled: false,
          },
    ),
  );
  vi.stubGlobal("fetch", fetcher);
  let refresh!: PageProps["refresh"];
  function Page(props: PageProps) {
    refresh = props.refresh;
    return (
      <>
        <button
          onClick={() =>
            props.navigate("profiles", {
              id: record.id,
              version: 1,
              expectation: { scenario: record, after_scenario_revision: 1 },
            })
          }
        >
          Select exact receipt
        </button>
        <ProfilesPage {...props} />
      </>
    );
  }
  render(<Application pages={{ ...pages, profiles: Page }} />);
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: "New scenario" }));
  await user.type(
    screen.getByRole("textbox", { name: "Scenario name" }),
    "dirty literal",
  );
  // Native dialog inertness is separately admitted browser coverage.
  fireEvent.click(screen.getByRole("button", { name: "Select exact receipt" }));
  await waitFor(() =>
    expect(screen.getByTestId("scenario-readback-status")).toHaveAttribute(
      "data-readback",
      "receipt-confirmed",
    ),
  );
  expect(screen.getByRole("textbox", { name: "Scenario name" })).toHaveValue(
    "dirty literal",
  );
  vi.spyOn(api, "getWorkspace").mockRejectedValue(Error("outage"));
  await act(() => refresh().catch(() => undefined));
  expect(screen.getByRole("textbox", { name: "Scenario name" })).toBeDisabled();
  expect(
    screen.getByRole("button", {
      name: "Read selected scenario again (GET only)",
    }),
  ).toBeEnabled();
  expect(
    fetcher.mock.calls.filter(([u]) => u === `/api/v1/scenarios/${record.id}`),
  ).toHaveLength(1);
});
it("library uses selected exact shared history without a second history GET", async () => {
  window.history.replaceState(null, "", "/profiles");
  localStorage.setItem("aegis.locale", "en");
  const record = await recordFixture(),
    data = workspaceFixture();
  data.targets = [record.target_snapshot, record.sink_snapshot];
  vi.spyOn(api, "getWorkspace").mockResolvedValue(data);
  const fetcher = vi.fn(async (u: string) =>
    response(
      u.includes("?")
        ? {
            revision: 1,
            total: 1,
            offset: 0,
            limit: 50,
            items: [record],
            execution_enabled: false,
          }
        : {
            revision: 1,
            scenario_id: record.id,
            versions: [record],
            execution_enabled: false,
          },
    ),
  );
  vi.stubGlobal("fetch", fetcher);
  window.history.replaceState(
    null,
    "",
    `/profiles?scenario=${record.id}&version=1`,
  );
  render(<Application pages={pages} />);
  await waitFor(() =>
    expect(screen.getByTestId("scenario-readback-status")).toHaveAttribute(
      "data-readback",
      "current-only",
    ),
  );
  fireEvent.click(
    await screen.findByRole("button", { name: "Scenario history" }),
  );
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "Edit scenario" }),
    ).toBeInTheDocument(),
  );
  expect(
    fetcher.mock.calls.filter(([u]) => u === `/api/v1/scenarios/${record.id}`),
  ).toHaveLength(1);
});

import * as selectionCodec from "./pages/ai/chat-scenario-wire";
it("late receipt validation cannot navigate after Application unmount", async () => {
  window.history.replaceState(null, "", "/overview");
  localStorage.setItem("aegis.locale", "en");
  vi.spyOn(api, "getWorkspace").mockResolvedValue(workspaceFixture());
  const scenario = await recordFixture();
  let release!: () => void;
  const barrier = new Promise<void>((r) => {
    release = r;
  });
  const parse = selectionCodec.parseV4;
  vi.spyOn(selectionCodec, "parseV4").mockImplementation(
    async (name, value) => {
      const result = await parse(name, value);
      await barrier;
      return result;
    },
  );
  function Page({ navigate }: PageProps) {
    return (
      <button
        onClick={() =>
          navigate("profiles", {
            id: scenario.id,
            version: 1,
            expectation: { scenario, after_scenario_revision: 1 },
          })
        }
      >
        Delayed navigation
      </button>
    );
  }
  const view = render(<Application pages={{ ...pages, overview: Page }} />);
  fireEvent.click(
    await screen.findByRole("button", { name: "Delayed navigation" }),
  );
  view.unmount();
  await act(async () => {
    release();
    await new Promise((r) => setTimeout(r, 20));
  });
  expect(window.location.pathname).toBe("/overview");
});

// RB01: actual manual inspection precedes same-record selected ownership.
import { within } from "@testing-library/react";
it.each([
  "settle",
  "manual-cancel",
  "manual-failure",
  "selected-cancel",
  "replace",
  "drop",
  "unmount",
] as const)(
  "RB01 actual App manual-to-selected handoff retains the GET lease (%s)",
  async (kind) => {
    localStorage.setItem("aegis.locale", "en");
    window.history.replaceState(null, "", "/profiles");
    const first = await recordFixture(),
      second = await recordFixture(2);
    const data = workspaceFixture();
    data.targets = [first.target_snapshot, first.sink_snapshot];
    vi.spyOn(api, "getWorkspace").mockResolvedValue(data);
    const history = {
      revision: 2,
      scenario_id: first.id,
      versions: [first, second],
      execution_enabled: false,
    };
    let release!: (r: Response) => void, reject!: (e: Error) => void;
    let starts = 0,
      active = 0,
      maximum = 0;
    let manualSignal!: AbortSignal;
    const schedule: string[] = [];
    const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
      expect(init?.method).toBe("GET");
      if (url.includes("?"))
        return response({
          revision: 2,
          total: 1,
          offset: 0,
          limit: 50,
          items: [second],
          execution_enabled: false,
        });
      starts++;
      active++;
      maximum = Math.max(maximum, active);
      const ordinal = starts;
      schedule.push("start:" + ordinal);
      try {
        if (ordinal === 1) {
          manualSignal = init!.signal!;
          return await new Promise<Response>((yes, no) => {
            release = yes;
            reject = no;
          });
        }
        return response(history);
      } finally {
        active--;
        schedule.push("retire:" + ordinal);
      }
    });
    vi.stubGlobal("fetch", fetcher);
    const view = render(<Application pages={pages} />);
    fireEvent.click(
      await screen.findByRole("button", { name: "Scenario history" }),
    );
    await waitFor(() => expect(starts).toBe(1));
    const select = (version?: number) =>
      act(() => {
        window.history.replaceState(
          null,
          "",
          version
            ? `/profiles?scenario=${first.id}&version=${version}`
            : "/profiles",
        );
        window.dispatchEvent(new PopStateEvent("popstate"));
      });
    if (kind === "manual-cancel")
      fireEvent.click(
        within(
          screen.getByRole("dialog", { name: "Scenario history" }),
        ).getByRole("button", { name: "Close" }),
      );
    select(1);
    if (kind === "replace") {
      select(2);
      select(1);
    }
    if (kind === "selected-cancel")
      fireEvent.click(
        screen.getByRole("button", { name: "Cancel scenario inspection" }),
      );
    if (kind === "drop") select();
    if (kind === "unmount") view.unmount();
    await act(async () => {
      await new Promise((r) => setTimeout(r, 30));
    });
    expect(starts).toBe(1);
    expect(manualSignal.aborted).toBe(false);
    await act(async () => {
      if (kind === "manual-failure")
        reject(Error("scripted manual read failure"));
      else release(response(history));
    });
    if (["selected-cancel", "drop", "unmount"].includes(kind)) {
      await act(async () => {
        await new Promise((r) => setTimeout(r, 30));
      });
      expect(starts).toBe(1);
    } else {
      await waitFor(() =>
        expect(
          screen.getByTestId("scenario-readback-status"),
        ).toHaveAttribute("data-readback", "current-only"),
      );
      expect(starts).toBe(2);
      expect(schedule).toEqual([
        "start:1",
        "retire:1",
        "start:2",
        "retire:2",
      ]);
      if (kind !== "manual-cancel") {
        const dialog = screen.getByRole("dialog", {
          name: "Scenario history",
        });
        expect(
          within(dialog).getByRole("combobox", { name: "Revision" }),
        ).toHaveValue("1");
      }
      // The manual codec's latest record is not substituted for selected v1.
      const selected = screen.getByRole("region", {
        name: "Selected scenario version",
      });
      expect(within(selected).getByText(first.digest)).toBeInTheDocument();
      expect(within(selected).queryByText(second.digest)).toBeNull();
      fireEvent.change(
        screen.getByRole("combobox", { name: "Interface language" }),
        { target: { value: "ko" } },
      );
      await act(async () => {
        await new Promise((r) => setTimeout(r, 30));
      });
      expect(starts).toBe(2);
    }
    expect(maximum).toBe(1);
    expect(active).toBe(0);
  },
);

it("RB01 actual App waits for the manual U0 deadline, then supports read-only selected Retry", async () => {
  localStorage.setItem("aegis.locale", "en");
  window.history.replaceState(null, "", "/profiles");
  const record = await recordFixture();
  const body = {
    revision: 1,
    scenario_id: record.id,
    versions: [record],
    execution_enabled: false,
  };
  const data = workspaceFixture();
  data.targets = []; // Inspection does not depend on current target eligibility.
  vi.spyOn(api, "getWorkspace").mockResolvedValue(data);
  let transport!: AbortSignal,
    starts = 0;
  const schedule: string[] = [];
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    expect(init?.method).toBe("GET");
    if (url.includes("?"))
      return response({
        revision: 1,
        total: 1,
        offset: 0,
        limit: 50,
        items: [record],
        execution_enabled: false,
      });
    starts++;
    if (starts === 1) {
      transport = init!.signal!;
      schedule.push("manual:start");
      transport.addEventListener("abort", () =>
        schedule.push("manual:deadline"),
      );
      return new Promise<Response>(() => {});
    }
    expect(transport.aborted).toBe(true);
    schedule.push("selected:" + starts);
    if (starts === 2) throw Error("scripted selected outage");
    return response(body);
  });
  vi.stubGlobal("fetch", fetcher);
  const view = render(<Application pages={pages} />);
  const history = await screen.findByRole("button", {
    name: "Scenario history",
  });
  vi.useFakeTimers();
  try {
    fireEvent.click(history);
    expect(starts).toBe(1);
    act(() => {
      window.history.replaceState(
        null,
        "",
        `/profiles?scenario=${record.id}&version=1`,
      );
      window.dispatchEvent(new PopStateEvent("popstate"));
    });
    await act(() => vi.advanceTimersByTimeAsync(9999));
    expect(starts).toBe(1);
    expect(transport.aborted).toBe(false);
    await act(() => vi.advanceTimersByTimeAsync(1));
    expect(schedule).toEqual([
      "manual:start",
      "manual:deadline",
      "selected:2",
    ]);
    expect(screen.getByTestId("scenario-readback-status")).toHaveAttribute(
      "data-readback",
      "unavailable",
    );
    await act(() => vi.advanceTimersByTimeAsync(10000));
    expect(starts).toBe(2); // No automatic retry.
    vi.useRealTimers();
    const retry = screen.getByRole("button", {
      name: "Read selected scenario again (GET only)",
    });
    expect(retry.closest("fieldset")).toBeNull();
    fireEvent.click(retry);
    await waitFor(() =>
      expect(
        screen.getByTestId("scenario-readback-status"),
      ).toHaveAttribute("data-readback", "current-only"),
    );
    expect(starts).toBe(3);
    expect(
      within(
        screen.getByRole("region", { name: "Selected scenario version" }),
      ).getByText(record.digest),
    ).toBeInTheDocument();
    view.unmount();
  } finally {
    vi.useRealTimers();
  }
});
it.each(["throw", "reject"] as const)(
  "RB01 manual inspection callback %s remains read-only and explicitly retryable",
  async (kind) => {
    localStorage.setItem("aegis.locale", "en");
    window.history.replaceState(null, "", "/profiles");
    const record = await recordFixture();
    const body = {
      revision: 1,
      scenario_id: record.id,
      versions: [record],
      execution_enabled: false,
    };
    const data = workspaceFixture();
    data.targets = [record.target_snapshot, record.sink_snapshot];
    vi.spyOn(api, "getWorkspace").mockResolvedValue(data);
    const callback = vi
      .fn<NonNullable<PageProps["readScenarioHistory"]>>()
      .mockImplementationOnce(() => {
        if (kind === "throw") throw Error("scripted callback throw");
        return Promise.reject(Error("scripted callback rejection"));
      })
      .mockResolvedValue({ ...body, execution_enabled: false });
    function Page(props: PageProps) {
      return <ProfilesPage {...props} readScenarioHistory={callback} />;
    }
    const fetcher = vi.fn(async () =>
      response({
        revision: 1,
        total: 1,
        offset: 0,
        limit: 50,
        items: [record],
        execution_enabled: false,
      }),
    );
    vi.stubGlobal("fetch", fetcher);
    render(<Application pages={{ ...pages, profiles: Page }} />);
    fireEvent.click(
      await screen.findByRole("button", { name: "Scenario history" }),
    );
    expect(
      await screen.findByText(
        "History could not be read. Editing is disabled.",
      ),
    ).toBeInTheDocument();
    expect(callback).toHaveBeenCalledTimes(1);
    fireEvent.click(
      screen.getByRole("button", { name: "Retry history read" }),
    );
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Edit scenario" }),
      ).toBeEnabled(),
    );
    expect(callback).toHaveBeenCalledTimes(2);
    expect(fetcher).toHaveBeenCalledTimes(1); // Only the original page GET; no writes.
  },
);

// RB02: retiring a view must not leave Loading without owned publishable work.
function rb02Select(id?: string) {
  act(() => {
    window.history.replaceState(
      null,
      "",
      id ? `/profiles?scenario=${id}&version=1` : "/profiles",
    );
    window.dispatchEvent(new PopStateEvent("popstate"));
  });
}
const rb02Tick = () =>
  new Promise<void>((resolve) => setTimeout(resolve, 30));
function rb02Deferred() {
  let resolve!: (value: Response) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<Response>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}
async function rb02App(selected = false, different = false) {
  localStorage.setItem("aegis.locale", "en");
  const first = await recordFixture(),
    second = await recordFixture(2);
  const other = await recordFixture(1, {
    id: "22222222-2222-4222-8222-222222222222",
  });
  window.history.replaceState(
    null,
    "",
    selected ? `/profiles?scenario=${first.id}&version=1` : "/profiles",
  );
  const data = workspaceFixture();
  data.targets = [first.target_snapshot, first.sink_snapshot];
  vi.spyOn(api, "getWorkspace").mockResolvedValue(data);
  const history = {
    revision: different ? 3 : 2,
    scenario_id: first.id,
    versions: [first, second],
    execution_enabled: false,
  };
  const pending = [rb02Deferred(), rb02Deferred(), rb02Deferred()];
  const signals: AbortSignal[] = [],
    urls: string[] = [],
    schedule: string[] = [];
  let active = 0,
    maximum = 0;
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    expect(init?.method).toBe("GET");
    if (url.includes("?"))
      return response({
        revision: history.revision,
        total: different ? 2 : 1,
        offset: 0,
        limit: 50,
        items: different ? [second, other] : [second],
        execution_enabled: false,
      });
    urls.push(url);
    signals.push(init!.signal!);
    const ordinal = urls.length;
    active++;
    maximum = Math.max(maximum, active);
    schedule.push("start:" + ordinal);
    try {
      return await pending[ordinal - 1].promise;
    } finally {
      active--;
      schedule.push("retire:" + ordinal);
    }
  });
  vi.stubGlobal("fetch", fetcher);
  const view = render(<Application pages={pages} />);
  const buttons = await screen.findAllByRole("button", {
    name: "Scenario history",
  });
  const dialog = () =>
    within(screen.getByRole("dialog", { name: "Scenario history" }));
  const retryable = () => {
    expect(dialog().queryByText("Loading history…")).toBeNull();
    expect(
      dialog().getByText("History could not be read. Editing is disabled."),
    ).toBeInTheDocument();
    expect(
      dialog().getByRole("button", { name: "Retry history read" }),
    ).toBeEnabled();
    expect(dialog().queryByRole("combobox", { name: "Revision" })).toBeNull();
    expect(dialog().queryByText(first.digest)).toBeNull();
    expect(dialog().queryByText(second.digest)).toBeNull();
  };
  const noSaved = () =>
    expect(
      screen.queryByText(
        "Scenario saved and verified in immutable history. No execution was started.",
      ),
    ).toBeNull();
  return {
    first,
    second,
    other,
    history,
    pending,
    signals,
    urls,
    schedule,
    view,
    buttons,
    dialog,
    retryable,
    noSaved,
    counts: () => ({ active, maximum }),
  };
}
it.each([
  "late-success",
  "late-error",
  "retry-success",
  "retry-error",
  "repeat",
  "close",
  "unmount",
] as const)(
  "RB02 actual App retired manual view is explicitly retryable without releasing the lease (%s)",
  async (kind) => {
    const h = await rb02App();
    fireEvent.click(h.buttons[0]);
    expect(h.urls).toHaveLength(1);
    rb02Select(h.first.id);
    rb02Select();
    h.retryable();
    expect(screen.queryByTestId("scenario-readback-status")).toBeNull();
    await act(rb02Tick);
    expect(h.urls).toHaveLength(1);
    expect(h.signals[0].aborted).toBe(false);
    const retry = !kind.startsWith("late-");
    if (retry) {
      fireEvent.click(
        h.dialog().getByRole("button", { name: "Retry history read" }),
      );
      expect(h.dialog().getByText("Loading history…")).toBeInTheDocument();
      if (kind === "repeat") {
        rb02Select(h.first.id);
        rb02Select();
        h.retryable();
        fireEvent.click(
          h.dialog().getByRole("button", { name: "Retry history read" }),
        );
      }
      if (kind === "close")
        fireEvent.click(h.dialog().getByRole("button", { name: "Close" }));
      if (kind === "unmount") h.view.unmount();
      await act(rb02Tick);
      expect(h.urls).toHaveLength(1);
      expect(h.signals[0].aborted).toBe(false);
    }
    await act(async () => {
      if (kind.endsWith("error"))
        h.pending[0].reject(Error("late retired manual failure"));
      else h.pending[0].resolve(response(h.history));
    });
    await act(rb02Tick);
    if (retry && kind !== "close" && kind !== "unmount") {
      await waitFor(() => expect(h.urls).toHaveLength(2));
      // The retired callback must neither publish nor overwrite the new loader.
      expect(h.dialog().getByText("Loading history…")).toBeInTheDocument();
      expect(h.dialog().queryByText(h.second.digest)).toBeNull();
      expect(h.schedule).toEqual(["start:1", "retire:1", "start:2"]);
      await act(async () => {
        h.pending[1].resolve(response(h.history));
      });
      await waitFor(() =>
        expect(
          h.dialog().getByRole("combobox", { name: "Revision" }),
        ).toHaveValue("2"),
      );
      expect(h.dialog().getByText(h.second.digest)).toBeInTheDocument();
      expect(h.urls).toEqual([
        `/api/v1/scenarios/${h.first.id}`,
        `/api/v1/scenarios/${h.first.id}`,
      ]);
    } else {
      expect(h.urls).toHaveLength(1);
      if (kind.startsWith("late-")) h.retryable();
      else
        expect(
          screen.queryByRole("dialog", { name: "Scenario history" }),
        ).toBeNull();
    }
    h.noSaved();
    expect(h.counts()).toEqual({ active: 0, maximum: 1 });
  },
);
it.each(["open", "reopen"] as const)(
  "RB02 actual App already-selected history %s settles on drop even without a new selected-version effect",
  async (kind) => {
    const h = await rb02App(true);
    fireEvent.click(h.buttons[0]);
    if (kind === "reopen") {
      fireEvent.click(h.dialog().getByRole("button", { name: "Close" }));
      fireEvent.click(h.buttons[0]);
    }
    expect(h.urls).toHaveLength(1);
    rb02Select();
    h.retryable();
    fireEvent.click(
      h.dialog().getByRole("button", { name: "Retry history read" }),
    );
    await act(rb02Tick);
    expect(h.urls).toHaveLength(1);
    expect(h.signals[0].aborted).toBe(false);
    await act(async () => {
      h.pending[0].resolve(response(h.history));
    });
    await waitFor(() => expect(h.urls).toHaveLength(2));
    expect(h.dialog().queryByText(h.first.digest)).toBeNull();
    expect(h.dialog().getByText("Loading history…")).toBeInTheDocument();
    await act(async () => {
      h.pending[1].resolve(response(h.history));
    });
    await waitFor(() =>
      expect(
        h.dialog().getByRole("combobox", { name: "Revision" }),
      ).toHaveValue("2"),
    );
    expect(screen.queryByTestId("scenario-readback-status")).toBeNull();
    expect(h.schedule).toEqual([
      "start:1",
      "retire:1",
      "start:2",
      "retire:2",
    ]);
    h.noSaved();
    expect(h.counts()).toEqual({ active: 0, maximum: 1 });
  },
);
it.each(["same-record", "different-record"] as const)(
  "RB02 actual App preserves completed manual history across %s selection and drop",
  async (kind) => {
    const h = await rb02App(false, true);
    fireEvent.click(h.buttons[0]);
    await act(async () => {
      h.pending[0].resolve(response(h.history));
    });
    await waitFor(() =>
      expect(
        h.dialog().getByRole("combobox", { name: "Revision" }),
      ).toHaveValue("2"),
    );
    rb02Select(kind === "same-record" ? h.first.id : h.other.id);
    rb02Select();
    expect(
      h.dialog().getByRole("combobox", { name: "Revision" }),
    ).toHaveValue("2");
    expect(
      h
        .dialog()
        .getByText(h.second.digest),
    ).toBeInTheDocument();
    expect(
      h.dialog().queryByRole("button", { name: "Retry history read" }),
    ).toBeNull();
    await act(async () => {
      h.pending[1].resolve(
        response(
          kind === "same-record"
            ? h.history
            : { ...h.history, scenario_id: h.other.id, versions: [h.other] },
        ),
      );
    });
    await act(rb02Tick);
    expect(h.urls).toHaveLength(2);
    expect(screen.queryByTestId("scenario-readback-status")).toBeNull();
    h.noSaved();
    expect(h.counts()).toEqual({ active: 0, maximum: 1 });
  },
);
it("RB02 actual App different-record selection does not retire a pending manual view", async () => {
  const h = await rb02App(false, true);
  fireEvent.click(h.buttons[0]);
  rb02Select(h.other.id);
  rb02Select();
  expect(h.dialog().getByText("Loading history…")).toBeInTheDocument();
  expect(h.urls).toHaveLength(1);
  expect(h.signals[0].aborted).toBe(false);
  await act(async () => {
    h.pending[0].resolve(response(h.history));
  });
  await waitFor(() =>
    expect(
      h.dialog().getByRole("combobox", { name: "Revision" }),
    ).toHaveValue("2"),
  );
  expect(h.dialog().getByText(h.second.digest)).toBeInTheDocument();
  await act(rb02Tick);
  expect(h.urls).toHaveLength(1);
  h.noSaved();
  expect(h.counts()).toEqual({ active: 0, maximum: 1 });
});

// RB03: a dialog choice belongs to its history source, not App's selection.
function rb03Select(id?: string, version = 2) {
  act(() => {
    window.history.replaceState(
      null,
      "",
      id ? `/profiles?scenario=${id}&version=${version}` : "/profiles",
    );
    window.dispatchEvent(new PopStateEvent("popstate"));
  });
}
it("RB03 actual App restores chosen manual v1 even when selected v2 is in range", async () => {
  const h = await rb02App();
  fireEvent.click(h.buttons[0]);
  await act(async () => {
    h.pending[0].resolve(response(h.history));
  });
  await waitFor(() =>
    expect(
      h.dialog().getByRole("combobox", { name: "Revision" }),
    ).toHaveValue("2"),
  );
  fireEvent.change(h.dialog().getByRole("combobox", { name: "Revision" }), {
    target: { value: "1" },
  });
  expect(h.dialog().getByText(h.first.digest)).toBeInTheDocument();
  rb03Select(h.first.id);
  await act(async () => {
    h.pending[1].resolve(response(h.history));
  });
  await waitFor(() =>
    expect(screen.getByTestId("scenario-readback-status")).toHaveAttribute(
      "data-readback",
      "current-only",
    ),
  );
  expect(
    h.dialog().getByRole("combobox", { name: "Revision" }),
  ).toHaveValue("2");
  expect(h.dialog().getByText(h.second.digest)).toBeInTheDocument();
  rb03Select();
  expect(
    h.dialog().getByRole("combobox", { name: "Revision" }),
  ).toHaveValue("1");
  expect(h.dialog().getByText(h.first.digest)).toBeInTheDocument();
  expect(
    h.dialog().getByRole("button", { name: "Edit scenario" }),
  ).toBeDisabled();
  expect(screen.queryByTestId("scenario-readback-status")).toBeNull();
  await act(rb02Tick);
  expect(h.urls).toHaveLength(2);
  expect(h.schedule).toEqual([
    "start:1",
    "retire:1",
    "start:2",
    "retire:2",
  ]);
  expect(h.counts()).toEqual({ active: 0, maximum: 1 });
  h.noSaved();
});

// These finite compatibility controls follow the state-ownership RED/GREEN.
// They exercise actual App/Profiles/Library and both history codecs, not stubs.
it.each([
  "same-version-control",
  "newer-pending-drop",
  "newer-completed-drop",
] as const)(
  "RB03 actual App retains completed v1 snapshot after %s",
  async (kind) => {
    localStorage.setItem("aegis.locale", "en");
    window.history.replaceState(null, "", "/profiles");
    const first = await recordFixture(),
      second = await recordFixture(2);
    const data = workspaceFixture();
    data.targets = [first.target_snapshot, first.sink_snapshot];
    vi.spyOn(api, "getWorkspace").mockResolvedValue(data);
    const original = {
      revision: 1,
      scenario_id: first.id,
      versions: [first],
      execution_enabled: false,
    };
    const appended = {
      ...original,
      revision: 2,
      versions: [first, second],
    };
    const held = rb02Deferred();
    let count = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        expect(init?.method).toBe("GET");
        if (url.includes("?"))
          return response({
            revision: 1,
            total: 1,
            offset: 0,
            limit: 50,
            items: [first],
            execution_enabled: false,
          });
        return ++count === 1 ? response(original) : held.promise;
      }),
    );
    render(<Application pages={pages} />);
    fireEvent.click(
      await screen.findByRole("button", { name: "Scenario history" }),
    );
    const dialog = () =>
      within(screen.getByRole("dialog", { name: "Scenario history" }));
    await waitFor(() =>
      expect(
        dialog().getByRole("combobox", { name: "Revision" }),
      ).toHaveValue("1"),
    );
    const version = kind === "same-version-control" ? 1 : 2;
    rb03Select(first.id, version);
    expect(count).toBe(2);
    if (kind !== "newer-pending-drop") {
      await act(async () => {
        held.resolve(response(appended));
      });
      await waitFor(() =>
        expect(
          screen.getByTestId("scenario-readback-status"),
        ).toHaveAttribute("data-readback", "current-only"),
      );
      expect(
        dialog().getByRole("combobox", { name: "Revision" }),
      ).toHaveValue(String(version));
      expect(
        dialog().getByText(version === 1 ? first.digest : second.digest),
      ).toBeInTheDocument();
    }
    rb03Select();
    expect(
      dialog().getByRole("combobox", { name: "Revision" }),
    ).toHaveValue("1");
    expect(dialog().getByText(first.digest)).toBeInTheDocument();
    expect(dialog().queryByText(second.digest)).toBeNull();
    expect(
      dialog().getByRole("button", { name: "Edit scenario" }),
    ).toBeEnabled();
    expect(screen.queryByTestId("scenario-readback-status")).toBeNull();
    if (kind === "newer-pending-drop")
      await act(async () => {
        held.resolve(response(appended));
      });
    await act(rb02Tick);
    expect(count).toBe(2);
    expect(
      dialog().getByRole("combobox", { name: "Revision" }),
    ).toHaveValue("1");
    expect(dialog().getByText(first.digest)).toBeInTheDocument();
    fireEvent.click(
      dialog().getByRole("button", { name: "Edit scenario" }),
    );
    const editor = within(
      screen.getByRole("dialog", { name: "Edit scenario" }),
    );
    expect(
      editor.getByText("Opening registry revision: 1"),
    ).toBeInTheDocument();
    expect(
      editor.getByRole("textbox", { name: "Scenario name" }),
    ).toHaveValue(first.definition.name);
    expect(count).toBe(2);
  },
);

async function rb03App(count = 2) {
  localStorage.setItem("aegis.locale", "en");
  window.history.replaceState(null, "", "/profiles");
  const records = await Promise.all(
    Array.from({ length: count }, (_, i) => recordFixture(i + 1)),
  );
  const others = await Promise.all(
    [1, 2].map((version) =>
      recordFixture(version, {
        id: "22222222-2222-4222-8222-222222222222",
      }),
    ),
  );
  const data = workspaceFixture();
  data.targets = [records[0].target_snapshot, records[0].sink_snapshot];
  vi.spyOn(api, "getWorkspace").mockResolvedValue(data);
  const history = {
    revision: count + 2,
    scenario_id: records[0].id,
    versions: records,
    execution_enabled: false,
  };
  const otherHistory = {
    ...history,
    scenario_id: others[0].id,
    versions: others,
  };
  const pending: ReturnType<typeof rb02Deferred>[] = [];
  const urls: string[] = [];
  let active = 0,
    maximum = 0;
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    expect(init?.method).toBe("GET");
    if (url.includes("?"))
      return response({
        revision: history.revision,
        total: 2,
        offset: 0,
        limit: 50,
        items: [records[count - 1], others[1]],
        execution_enabled: false,
      });
    urls.push(url);
    const held = rb02Deferred();
    pending.push(held);
    maximum = Math.max(maximum, ++active);
    try {
      return await held.promise;
    } finally {
      active--;
    }
  });
  vi.stubGlobal("fetch", fetcher);
  function Page(props: PageProps) {
    return (
      <>
        <button
          onClick={() =>
            props.navigate("profiles", {
              id: records[0].id,
              version: count,
              expectation: {
                scenario: records[count - 1],
                after_scenario_revision: history.revision,
              },
            })
          }
        >
          RB03 exact receipt
        </button>
        <ProfilesPage {...props} />
      </>
    );
  }
  const view = render(<Application pages={{ ...pages, profiles: Page }} />);
  const buttons = await screen.findAllByRole("button", {
    name: "Scenario history",
  });
  const dialog = () =>
    within(screen.getByRole("dialog", { name: "Scenario history" }));
  const selected = () =>
    within(
      screen.getByRole("region", { name: "Selected scenario version" }),
    );
  const settle = async (index: number, value = history) => {
    await waitFor(() => expect(pending).toHaveLength(index + 1));
    await act(async () => {
      pending[index].resolve(response(value));
    });
  };
  const choice = (version: number) =>
    fireEvent.change(dialog().getByRole("combobox", { name: "Revision" }), {
      target: { value: String(version) },
    });
  const shown = (version: number, record = records[version - 1]) => {
    expect(
      dialog().getByRole("combobox", { name: "Revision" }),
    ).toHaveValue(String(version));
    expect(dialog().getByText(record.digest)).toBeInTheDocument();
  };
  const status = async (state: string) =>
    waitFor(() =>
      expect(
        screen.getByTestId("scenario-readback-status"),
      ).toHaveAttribute("data-readback", state),
    );
  return {
    records,
    others,
    history,
    otherHistory,
    pending,
    urls,
    fetcher,
    view,
    buttons,
    dialog,
    selected,
    settle,
    choice,
    shown,
    status,
    counts: () => ({ active, maximum }),
  };
}

it("RB03 actual App keeps receipt and dialog choices independent across repeated handoff drop and reopen", async () => {
  const h = await rb03App();
  fireEvent.click(h.buttons[0]);
  await h.settle(0);
  await waitFor(() => h.shown(2));
  h.choice(1);
  h.shown(1);
  fireEvent.click(
    screen.getByRole("button", { name: "RB03 exact receipt" }),
  );
  await h.settle(1);
  await h.status("receipt-confirmed");
  h.shown(2);
  h.choice(1);
  h.shown(1);
  expect(h.selected().getByText(h.records[1].digest)).toBeInTheDocument();
  expect(h.selected().queryByText(h.records[0].digest)).toBeNull();
  expect(window.location.search).toBe(
    `?scenario=${h.records[0].id}&version=2`,
  );
  expect(
    h.dialog().getByRole("button", { name: "Edit scenario" }),
  ).toBeDisabled();
  rb03Select();
  h.shown(1);
  h.choice(2);
  h.shown(2);
  rb03Select(h.records[0].id);
  await h.settle(2);
  await h.status("current-only");
  h.shown(2);
  h.choice(1);
  h.shown(1);
  fireEvent.click(h.dialog().getByRole("button", { name: "Close" }));
  fireEvent.click(h.buttons[0]);
  h.shown(2);
  expect(h.urls).toHaveLength(3);
  h.choice(1);
  rb03Select();
  h.shown(2);
  expect(
    h.dialog().getByRole("button", { name: "Edit scenario" }),
  ).toBeEnabled();
  await act(rb02Tick);
  expect(h.urls).toHaveLength(3);
  expect(h.counts()).toEqual({ active: 0, maximum: 1 });
  fireEvent.click(
    h.dialog().getByRole("button", { name: "Edit scenario" }),
  );
  const editor = within(
    screen.getByRole("dialog", { name: "Edit scenario" }),
  );
  expect(
    editor.getByText("Opening registry revision: 4"),
  ).toBeInTheDocument();
  expect(
    editor.getByRole("textbox", { name: "Scenario name" }),
  ).toHaveValue(h.records[1].definition.name);
});

it("RB03 actual App binds same ordinal choices to different record identities and explicit manual reads", async () => {
  const h = await rb03App();
  fireEvent.click(h.buttons[0]);
  await h.settle(0);
  await waitFor(() => h.shown(2));
  rb03Select(h.records[0].id);
  await h.settle(1);
  await h.status("current-only");
  h.choice(1);
  h.shown(1);
  rb03Select(h.others[0].id);
  h.shown(2);
  await h.settle(2, h.otherHistory);
  await h.status("current-only");
  fireEvent.click(h.dialog().getByRole("button", { name: "Close" }));
  fireEvent.click(h.buttons[1]);
  h.shown(2, h.others[1]);
  h.choice(1);
  h.shown(1, h.others[0]);
  rb03Select();
  expect(h.dialog().queryByRole("combobox")).toBeNull();
  expect(h.dialog().queryByText(h.records[1].digest)).toBeNull();
  expect(
    h.dialog().queryByRole("button", { name: "Edit scenario" }),
  ).toBeNull();
  expect(
    h.dialog().getByRole("button", { name: "Retry history read" }),
  ).toBeEnabled();
  await act(rb02Tick);
  expect(h.urls).toHaveLength(3);
  fireEvent.click(
    h.dialog().getByRole("button", { name: "Retry history read" }),
  );
  await h.settle(3, h.otherHistory);
  await waitFor(() => h.shown(2, h.others[1]));
  h.choice(1);
  rb03Select(h.records[0].id);
  await h.settle(4);
  await h.status("current-only");
  h.shown(1, h.others[0]);
  rb03Select();
  h.shown(1, h.others[0]);
  fireEvent.click(h.dialog().getByRole("button", { name: "Close" }));
  fireEvent.click(h.buttons[1]);
  expect(h.dialog().getByText("Loading history…")).toBeInTheDocument();
  await h.settle(5, h.otherHistory);
  await waitFor(() => h.shown(2, h.others[1]));
  expect(h.urls).toEqual(
    [
      h.records[0].id,
      h.records[0].id,
      h.others[0].id,
      h.others[0].id,
      h.records[0].id,
      h.others[0].id,
    ].map((id) => `/api/v1/scenarios/${id}`),
  );
  expect(h.counts()).toEqual({ active: 0, maximum: 1 });
});

it.each(["failure", "missing-member"] as const)(
  "RB03 actual App selected %s without manual snapshot remains truthful and explicitly retryable",
  async (kind) => {
    const h = await rb03App();
    rb03Select(h.records[0].id);
    fireEvent.click(h.buttons[0]);
    expect(h.dialog().getByText("Loading history…")).toBeInTheDocument();
    if (kind === "failure") {
      await act(async () => {
        h.pending[0].reject(Error("scripted selected read failure"));
      });
      await h.status("unavailable");
    } else {
      await h.settle(0, { ...h.history, versions: [h.records[0]] });
      await h.status("discrepancy");
    }
    expect(h.dialog().queryByRole("combobox")).toBeNull();
    expect(
      h.dialog().queryByRole("button", { name: "Edit scenario" }),
    ).toBeNull();
    expect(h.dialog().queryByText(h.records[1].digest)).toBeNull();
    await act(rb02Tick);
    expect(h.urls).toHaveLength(1);
    fireEvent.click(
      h.dialog().getByRole("button", { name: "Retry history read" }),
    );
    await h.settle(1);
    await h.status("current-only");
    h.shown(2);
    rb03Select();
    expect(h.dialog().queryByRole("combobox")).toBeNull();
    expect(
      h.dialog().getByRole("button", { name: "Retry history read" }),
    ).toBeEnabled();
    expect(screen.queryByTestId("scenario-readback-status")).toBeNull();
    fireEvent.click(
      h.dialog().getByRole("button", { name: "Retry history read" }),
    );
    await h.settle(2);
    await waitFor(() => h.shown(2));
    expect(h.counts()).toEqual({ active: 0, maximum: 1 });
  },
);

it("RB03 actual App browses all ten selected versions without changing receipt or manual choice across locale", async () => {
  const h = await rb03App(10);
  fireEvent.click(h.buttons[0]);
  await h.settle(0);
  await waitFor(() => h.shown(10));
  h.choice(3);
  h.shown(3);
  fireEvent.click(
    screen.getByRole("button", { name: "RB03 exact receipt" }),
  );
  await h.settle(1);
  await h.status("receipt-confirmed");
  h.shown(10);
  for (let version = 1; version <= 10; version++) {
    h.choice(version);
    h.shown(version);
    expect(
      h.dialog().getByRole("button", { name: "Edit scenario" }),
    ).toBeDisabled();
    expect(h.selected().getByText(h.records[9].digest)).toBeInTheDocument();
    expect(screen.getByTestId("scenario-readback-status")).toHaveAttribute(
      "data-readback",
      "receipt-confirmed",
    );
  }
  h.choice(4);
  fireEvent.change(
    screen.getByRole("combobox", { name: "Interface language" }),
    { target: { value: "ko" } },
  );
  const korean = within(
    screen.getByRole("dialog", { name: "시나리오 이력" }),
  );
  expect(korean.getByRole("combobox", { name: "리비전" })).toHaveValue("4");
  expect(korean.getByText(h.records[3].digest)).toBeInTheDocument();
  rb03Select();
  expect(korean.getByRole("combobox", { name: "리비전" })).toHaveValue("3");
  expect(korean.getByText(h.records[2].digest)).toBeInTheDocument();
  expect(
    korean.getByRole("button", { name: "시나리오 수정" }),
  ).toBeDisabled();
  await act(rb02Tick);
  expect(h.urls).toHaveLength(2);
  expect(h.counts()).toEqual({ active: 0, maximum: 1 });
});
