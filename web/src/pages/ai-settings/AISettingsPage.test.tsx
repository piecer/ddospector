import { StrictMode } from "react";
import userEvent from "@testing-library/user-event";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { AISettingsPage } from "./index";
import { workspaceFixture } from "../../test/fixtures";

const props = () => ({
  data: workspaceFixture(),
  locale: "en" as const,
  navigate: vi.fn(),
  refresh: vi.fn().mockResolvedValue(undefined),
});
import type {
  AIModelProfile,
  AISettingsInput,
  AISettingsSnapshot,
} from "./types";
const empty = (): AISettingsSnapshot => ({
  revision: 0,
  profiles: [],
  default_profile_id: null,
  agent_profile_id: null,
  updated_at: null,
  execution_enabled: false,
  connection_status: "not_tested",
});
const response = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}
function profile(overrides: Partial<AIModelProfile> = {}): AIModelProfile {
  return {
    id: "llm-test",
    name: "Review model",
    format: "openai",
    model: "manual-model-id",
    base_url: "https://models.example.test/v1",
    credential_env: "REVIEW_API_KEY",
    rate_per_second: 0,
    rate_per_minute: 0,
    context_window_k: 0,
    streaming: true,
    max_tokens: 0,
    max_tokens_field: "",
    thinking_type: "",
    reasoning_effort: "",
    retry: {
      connect: { attempts: 0, interval_ms: 0 },
      empty: { attempts: 0, interval_ms: 0 },
      stream: { attempts: 0, interval_ms: 0 },
    },
    ...overrides,
  };
}
function editField(name: string, value: string) {
  fireEvent.change(screen.getByLabelText(name), { target: { value } });
}
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  vi.useRealTimers();
});

it("creates a stable draft with exact defaults and adopts only the PUT receipt", async () => {
  const inputs: AISettingsInput[] = [];
  const fetcher = vi.fn(async (_url: string, init: RequestInit) => {
    if (init.method === "GET") return response({ ...empty(), revision: 7 });
    const input = JSON.parse(init.body as string) as AISettingsInput;
    inputs.push(input);
    return response({
      ...empty(),
      ...input,
      revision: 8,
      profiles: [{ ...input.profiles[0], name: "Authoritative name" }],
    });
  });
  vi.stubGlobal("fetch", fetcher);
  const storage = vi.spyOn(Storage.prototype, "setItem");
  render(<AISettingsPage {...props()} />);
  await screen.findByText("No model profiles yet");
  fireEvent.click(screen.getByRole("button", { name: "Create profile" }));
  const dialog = screen.getByRole("dialog", { name: "Create model profile" });
  expect(dialog.tagName).toBe("DIALOG");
  const id = within(dialog).getByLabelText("Profile ID").textContent!;
  expect(id).toMatch(/^llm-[0-9a-f-]{36}$/);
  editField("Profile name", "My draft");
  editField("Model ID", "literal/model:2026");
  editField("Base URL", "https://models.example.test/v1");
  editField("Credential environment variable", "REVIEW_API_KEY");
  expect(within(dialog).getByLabelText("Profile ID")).toHaveTextContent(id);
  expect(dialog.querySelector('input[type="password"]')).toBeNull();
  fireEvent.click(within(dialog).getByRole("button", { name: "Save profile" }));
  await screen.findByRole("heading", { name: "Authoritative name" });
  expect(inputs).toEqual([
    {
      revision: 7,
      profiles: [
        profile({ id, name: "My draft", model: "literal/model:2026" }),
      ],
      default_profile_id: null,
      agent_profile_id: null,
    },
  ]);
  expect(fetcher).toHaveBeenCalledTimes(2);
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(screen.getByRole("status")).toHaveTextContent("Draft settings saved");
  expect(storage).not.toHaveBeenCalled();
});

it("edits independent advanced fields and clears the Chat-only output field", async () => {
  const initial = {
    ...empty(),
    revision: 2,
    profiles: [
      profile({ max_tokens_field: "max_completion_tokens", max_tokens: 900 }),
    ],
  };
  let submitted: AISettingsInput | undefined;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_url: string, init: RequestInit) => {
      if (init.method === "GET") return response(initial);
      submitted = JSON.parse(init.body as string) as AISettingsInput;
      return response({ ...initial, ...submitted, revision: 3 });
    }),
  );
  render(<AISettingsPage {...props()} />);
  await screen.findByRole("heading", { name: "Review model" });
  fireEvent.click(screen.getByRole("button", { name: "Edit Review model" }));
  const advanced = screen.getByText("Advanced settings").closest("details")!;
  expect(advanced.open).toBe(false);
  fireEvent.click(screen.getByText("Advanced settings"));
  editField("Requests per second", "12");
  editField("Requests per minute", "123");
  editField("Context capacity (K tokens)", "64");
  editField("Output token limit", "800");
  fireEvent.click(screen.getByRole("checkbox", { name: "Streaming" }));
  editField("Thinking", "enabled");
  editField("Reasoning effort", "xhigh");
  editField("Protocol", "anthropic");
  expect(screen.getByLabelText("Output token field")).toHaveValue("");
  expect(screen.getByLabelText("Output token field")).toBeDisabled();
  expect(screen.getByText(/Switching away clears/)).toBeVisible();
  fireEvent.click(screen.getByText("Retry policy"));
  editField("Connect attempts", "-1");
  editField("Empty attempts", "2");
  editField("Empty interval (ms)", "200");
  editField("Stream attempts", "3");
  editField("Stream interval (ms)", "1000");
  fireEvent.click(screen.getByRole("button", { name: "Save profile" }));
  await waitFor(() => expect(submitted).toBeDefined());
  expect(submitted?.profiles).toEqual([
    profile({
      format: "anthropic",
      rate_per_second: 12,
      rate_per_minute: 123,
      context_window_k: 64,
      streaming: false,
      max_tokens: 800,
      max_tokens_field: "",
      thinking_type: "enabled",
      reasoning_effort: "xhigh",
      retry: {
        connect: { attempts: -1, interval_ms: 0 },
        empty: { attempts: 2, interval_ms: 200 },
        stream: { attempts: 3, interval_ms: 1000 },
      },
    }),
  ]);
  await waitFor(() =>
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
  );
  fireEvent.click(screen.getByRole("button", { name: "Create profile" }));
  fireEvent.click(screen.getByText("Advanced settings"));
  expect(screen.getByLabelText("Output token limit")).toHaveValue("0");
});

it("saves explicit bindings, blocks referenced deletion and confirms an unbound delete", async () => {
  let current = { ...empty(), profiles: [profile()] };
  const writes: AISettingsInput[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_url: string, init: RequestInit) => {
      if (init.method === "GET") return response(current);
      const input = JSON.parse(init.body as string) as AISettingsInput;
      writes.push(input);
      current = { ...current, ...input, revision: current.revision + 1 };
      return response(current);
    }),
  );
  render(<AISettingsPage {...props()} />);
  await screen.findByRole("heading", { name: "Review model" });
  expect(screen.getByLabelText("Default draft")).toHaveValue("");
  expect(screen.getByLabelText("Review-agent draft")).toHaveValue("");
  editField("Default draft", "llm-test");
  editField("Review-agent draft", "llm-test");
  fireEvent.click(screen.getByRole("button", { name: "Save bindings" }));
  await waitFor(() => expect(writes).toHaveLength(1));
  expect(writes[0]).toMatchObject({
    revision: 0,
    default_profile_id: "llm-test",
    agent_profile_id: "llm-test",
  });
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "Delete Review model" }),
    ).toBeDisabled(),
  );
  editField("Default draft", "");
  editField("Review-agent draft", "");
  fireEvent.click(screen.getByRole("button", { name: "Save bindings" }));
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "Delete Review model" }),
    ).toBeEnabled(),
  );
  fireEvent.click(screen.getByRole("button", { name: "Delete Review model" }));
  const dialog = screen.getByRole("dialog", { name: "Delete model profile" });
  expect(writes).toHaveLength(2);
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Delete profile" }),
  );
  await screen.findByText("No model profiles yet");
  expect(writes[2]).toEqual({
    revision: 2,
    profiles: [],
    default_profile_id: null,
    agent_profile_id: null,
  });
});

it("caps creation at twenty profiles without preventing editing", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      response({
        ...empty(),
        profiles: Array.from({ length: 20 }, (_, i) =>
          profile({ id: "llm-" + i, name: "Profile " + i }),
        ),
      }),
    ),
  );
  render(<AISettingsPage {...props()} />);
  await screen.findByRole("heading", { name: "Profile 19" });
  expect(screen.getByRole("button", { name: "Create profile" })).toBeDisabled();
  expect(screen.getByText(/20-profile limit/)).toBeVisible();
  expect(screen.getByRole("button", { name: "Edit Profile 19" })).toBeEnabled();
  expect(
    screen.getByRole("button", { name: "Test connection" }),
  ).toBeDisabled();
  expect(
    screen.getByRole("button", { name: "Discover models" }),
  ).toBeDisabled();
});

it.each([
  ["Profile name", " spaced "],
  ["Profile name", "STRASSE"],
  ["Model ID", " bad-model "],
  ["Credential environment variable", "sk-secret"],
  ["Base URL", "https://@example.test"],
  ["Base URL", "https://user:pass@example.test"],
  ["Base URL", "https://%65xample.test"],
  ["Base URL", "https://example.test/?key=x"],
  ["Base URL", "https://example.test/#"],
  ["Base URL", "https://example.test:99999"],
  ["Requests per second", "1000001"],
  ["Requests per minute", "-1"],
  ["Context capacity (K tokens)", "31"],
  ["Context capacity (K tokens)", "1001"],
  ["Output token limit", "Infinity"],
  ["Output token limit", "1.5"],
  ["Output token limit", ""],
  ["Connect attempts", "21"],
  ["Empty attempts", "-2"],
  ["Stream interval (ms)", "3600001"],
])(
  "rejects invalid %s input %j without normalizing or sending it",
  async (label, value) => {
    const fetcher = vi.fn(async () =>
      response({ ...empty(), profiles: [profile({ name: "Straße" })] }),
    );
    vi.stubGlobal("fetch", fetcher);
    render(<AISettingsPage {...props()} />);
    await screen.findByRole("heading", { name: "Straße" });
    fireEvent.click(screen.getByRole("button", { name: "Create profile" }));
    editField("Profile name", "New draft");
    editField("Model ID", "manual-model-id");
    fireEvent.click(screen.getByText("Advanced settings"));
    fireEvent.click(screen.getByText("Retry policy"));
    editField(label, value);
    fireEvent.click(screen.getByRole("button", { name: "Save profile" }));
    expect(await screen.findByRole("alert")).toBeVisible();
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(screen.getByLabelText(label)).toHaveValue(value);
  },
);

it.each([409, 503])(
  "locks a failed save (%s) until an explicit read discards local edits",
  async (status) => {
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce(
        response({ ...empty(), revision: 4, profiles: [profile()] }),
      )
      .mockResolvedValueOnce(
        response(
          { code: status === 409 ? "AI_SETTINGS_CONFLICT" : "UNAVAILABLE" },
          status,
        ),
      )
      .mockResolvedValueOnce(
        response({
          ...empty(),
          revision: 8,
          profiles: [profile({ name: "Other saved work" })],
        }),
      );
    vi.stubGlobal("fetch", fetcher);
    render(<AISettingsPage {...props()} />);
    await screen.findByRole("heading", { name: "Review model" });
    fireEvent.click(screen.getByRole("button", { name: "Edit Review model" }));
    editField("Profile name", "Unsaved inspection");
    fireEvent.click(screen.getByRole("button", { name: "Save profile" }));
    const dialog = screen.getByRole("dialog");
    await waitFor(() =>
      expect(within(dialog).getByRole("alert")).toHaveTextContent(
        /Mutations are locked/,
      ),
    );
    expect(screen.getByLabelText("Profile name")).toHaveValue(
      "Unsaved inspection",
    );
    expect(screen.getByRole("button", { name: "Save profile" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Close" })).toBeEnabled();
    expect(fetcher).toHaveBeenCalledTimes(2);
    fireEvent.click(
      within(dialog).getByRole("button", {
        name: "Reload saved settings (discard local edits)",
      }),
    );
    await screen.findByRole("heading", { name: "Other saved work" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(fetcher).toHaveBeenCalledTimes(3);
    expect(fetcher.mock.calls[2][1].method).toBe("GET");
    expect(
      screen.getByRole("button", { name: "Create profile" }),
    ).toBeEnabled();
  },
);

it("shows a failed initial read as unavailable, with explicit read-only recovery", async () => {
  const fetcher = vi
    .fn()
    .mockRejectedValueOnce(new TypeError("offline"))
    .mockResolvedValueOnce(response(empty()));
  vi.stubGlobal("fetch", fetcher);
  render(<AISettingsPage {...props()} />);
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Unable to read AI settings",
  );
  expect(screen.queryByText("No model profiles yet")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Create profile" })).toBeDisabled();
  fireEvent.click(
    screen.getByRole("button", { name: "Reload saved settings" }),
  );
  await screen.findByText("No model profiles yet");
  expect(fetcher).toHaveBeenCalledTimes(2);
});

it("permits dismissal during a held PUT without a late response reopening or focusing the dialog", async () => {
  const held = deferred<Response>();
  const fetcher = vi
    .fn()
    .mockResolvedValueOnce(response({ ...empty(), profiles: [profile()] }))
    .mockReturnValueOnce(held.promise);
  vi.stubGlobal("fetch", fetcher);
  render(<AISettingsPage {...props()} />);
  await screen.findByRole("heading", { name: "Review model" });
  fireEvent.click(screen.getByRole("button", { name: "Edit Review model" }));
  editField("Profile name", "Late saved name");
  fireEvent.click(screen.getByRole("button", { name: "Save profile" }));
  expect(screen.getByRole("button", { name: "Save profile" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Close" }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  const elsewhere = document.createElement("button");
  document.body.append(elsewhere);
  elsewhere.focus();
  await act(async () =>
    held.resolve(
      response({
        ...empty(),
        revision: 1,
        profiles: [profile({ name: "Late saved name" })],
      }),
    ),
  );
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(document.activeElement).toBe(elsewhere);
  elsewhere.remove();
  expect(
    screen.getByRole("heading", { name: "Late saved name" }),
  ).toBeVisible();
});

it("times out a held save, explicitly recovers, and fences its late authoritative response", async () => {
  const held = deferred<Response>();
  const fetcher = vi
    .fn()
    .mockResolvedValueOnce(response({ ...empty(), profiles: [profile()] }))
    .mockReturnValueOnce(held.promise)
    .mockResolvedValueOnce(
      response({
        ...empty(),
        revision: 2,
        profiles: [profile({ name: "Recovery winner" })],
      }),
    );
  vi.stubGlobal("fetch", fetcher);
  render(<AISettingsPage {...props()} />);
  await screen.findByRole("heading", { name: "Review model" });
  fireEvent.click(screen.getByRole("button", { name: "Edit Review model" }));
  editField("Profile name", "Timed-out edit");
  vi.useFakeTimers();
  fireEvent.click(screen.getByRole("button", { name: "Save profile" }));
  await act(async () => {
    await vi.advanceTimersByTimeAsync(10_000);
  });
  expect(
    within(screen.getByRole("dialog")).getByRole("alert"),
  ).toHaveTextContent("Mutations are locked");
  expect(fetcher.mock.calls[1][1].signal.aborted).toBe(true);
  fireEvent.click(
    screen.getByRole("button", {
      name: "Reload saved settings (discard local edits)",
    }),
  );
  await act(async () => {
    await Promise.resolve();
  });
  vi.useRealTimers();
  await screen.findByRole("heading", { name: "Recovery winner" });
  fireEvent.click(screen.getByRole("button", { name: "Edit Recovery winner" }));
  editField("Profile name", "New local work");
  screen.getByLabelText("Profile name").focus();
  await act(async () =>
    held.resolve(
      response({
        ...empty(),
        revision: 1,
        profiles: [profile({ name: "Timed-out edit" })],
      }),
    ),
  );
  expect(screen.getByLabelText("Profile name")).toHaveValue("New local work");
  expect(screen.getByLabelText("Profile name")).toHaveFocus();
  expect(
    screen.getByRole("heading", { name: "Recovery winner" }),
  ).toBeVisible();
  expect(fetcher).toHaveBeenCalledTimes(3);
});

it("does not render untrusted extra credential fields as valid settings", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      response({
        ...empty(),
        profiles: [{ ...profile(), api_key: "NEVER_RENDER" }],
      }),
    ),
  );
  render(<AISettingsPage {...props()} />);
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Unable to read AI settings",
  );
  expect(
    screen.queryByRole("heading", { name: "Review model" }),
  ).not.toBeInTheDocument();
  expect(screen.queryByText("NEVER_RENDER")).not.toBeInTheDocument();
});

it("fences stale initial reads and aborts request ownership on unmount", async () => {
  const old = deferred<Response>();
  const latest = deferred<Response>();
  const fetcher = vi
    .fn()
    .mockReturnValueOnce(old.promise)
    .mockReturnValueOnce(latest.promise);
  vi.stubGlobal("fetch", fetcher);
  const view = render(
    <StrictMode>
      <AISettingsPage {...props()} />
    </StrictMode>,
  );
  expect(fetcher).toHaveBeenCalledTimes(2);
  expect(fetcher.mock.calls[0][1].signal.aborted).toBe(true);
  await act(async () =>
    latest.resolve(
      response({ ...empty(), profiles: [profile({ name: "Latest read" })] }),
    ),
  );
  await act(async () =>
    old.resolve(
      response({ ...empty(), profiles: [profile({ name: "Stale read" })] }),
    ),
  );
  expect(screen.getByRole("heading", { name: "Latest read" })).toBeVisible();
  expect(
    screen.queryByRole("heading", { name: "Stale read" }),
  ).not.toBeInTheDocument();
  const pending = deferred<Response>();
  fetcher.mockReturnValueOnce(pending.promise);
  fireEvent.click(screen.getByRole("button", { name: "Edit Latest read" }));
  editField("Profile name", "Abandoned mutation");
  fireEvent.click(screen.getByRole("button", { name: "Save profile" }));
  view.unmount();
  expect(fetcher.mock.calls[2][1].signal.aborted).toBe(true);
  await act(async () =>
    pending.resolve(
      response({ ...empty(), revision: 1, profiles: [profile()] }),
    ),
  );
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

it("keeps unsaved dialogs inside the global disabled boundary and permits native cancel", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(empty())));
  const input = props();
  const view = render(
    <fieldset data-testid="global-boundary">
      <AISettingsPage {...input} />
    </fieldset>,
  );
  await screen.findByText("No model profiles yet");
  fireEvent.click(screen.getByRole("button", { name: "Create profile" }));
  editField("Profile name", "Unsaved work");
  view.rerender(
    <fieldset data-testid="global-boundary" disabled>
      <AISettingsPage {...input} />
    </fieldset>,
  );
  const dialog = screen.getByRole("dialog");
  expect(dialog.closest("fieldset")).toBe(
    screen.getByTestId("global-boundary"),
  );
  expect(screen.getByLabelText("Profile name")).toBeDisabled();
  expect(screen.getByRole("button", { name: "Save profile" })).toBeDisabled();
  fireEvent(dialog, new Event("cancel", { cancelable: true }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

it("renders Korean controls, manual identifiers and the complete long endpoint", async () => {
  const longModel = "모델/" + "a".repeat(190);
  const longURL = "https://example.test/" + "path".repeat(100);
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      response({
        ...empty(),
        profiles: [
          profile({ name: "검토 모델", model: longModel, base_url: longURL }),
        ],
      }),
    ),
  );
  document.documentElement.lang = "ko";
  render(<AISettingsPage {...props()} locale="ko" />);
  await screen.findByRole("heading", { name: "검토 모델" });
  expect(screen.getByText(longModel)).toBeVisible();
  expect(screen.getByText(longURL)).toBeVisible();
  expect(screen.getByText(/실행한 적 없음/)).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "편집 검토 모델" }));
  expect(
    screen.getByRole("dialog", { name: "모델 프로필 편집" }),
  ).toBeVisible();
  expect(screen.getByLabelText("모델 ID")).toHaveValue(longModel);
  await userEvent.click(screen.getByText("고급 설정"));
  expect(screen.getByLabelText("추론 강도")).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "대화상자 닫기" }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  document.documentElement.lang = "en";
});

it("rejects a contradictory successful PUT revision without acknowledging a save", async () => {
  const fetcher = vi
    .fn()
    .mockResolvedValueOnce(
      response({ ...empty(), revision: 5, profiles: [profile()] }),
    )
    .mockResolvedValueOnce(
      response({
        ...empty(),
        revision: 5,
        profiles: [profile({ name: "Contradictory" })],
      }),
    );
  vi.stubGlobal("fetch", fetcher);
  render(<AISettingsPage {...props()} />);
  await screen.findByRole("heading", { name: "Review model" });
  fireEvent.click(screen.getByRole("button", { name: "Edit Review model" }));
  editField("Profile name", "My edit");
  fireEvent.click(screen.getByRole("button", { name: "Save profile" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Mutations are locked",
  );
  expect(screen.getByLabelText("Profile name")).toHaveValue("My edit");
  expect(screen.queryByText(/Draft settings saved/)).not.toBeInTheDocument();
});

it("accepts names measured in Unicode characters rather than UTF-16 units", async () => {
  const name = "🧠".repeat(100);
  const fetcher = vi.fn(async (_url: string, init: RequestInit) =>
    init.method === "GET"
      ? response(empty())
      : response({
          ...empty(),
          ...JSON.parse(init.body as string),
          revision: 1,
        }),
  );
  vi.stubGlobal("fetch", fetcher);
  render(<AISettingsPage {...props()} />);
  await screen.findByText("No model profiles yet");
  fireEvent.click(screen.getByRole("button", { name: "Create profile" }));
  await userEvent.type(screen.getByLabelText("Profile name"), name);
  expect(screen.getByLabelText("Profile name")).toHaveValue(name);
  editField("Model ID", "literal-model");
  fireEvent.click(screen.getByRole("button", { name: "Save profile" }));
  await screen.findByRole("heading", { name });
});

it("explains protocol resets before opening advanced settings and announces pending save inside the dialog", async () => {
  const held = deferred<Response>();
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValueOnce(
        response({
          ...empty(),
          profiles: [profile({ max_tokens_field: "max_completion_tokens" })],
        }),
      )
      .mockReturnValueOnce(held.promise),
  );
  render(<AISettingsPage {...props()} />);
  await screen.findByRole("heading", { name: "Review model" });
  fireEvent.click(screen.getByRole("button", { name: "Edit Review model" }));
  expect(screen.getByText(/Changing away from Chat Completions/)).toBeVisible();
  editField("Protocol", "openai-responses");
  fireEvent.click(screen.getByRole("button", { name: "Save profile" }));
  expect(
    within(screen.getByRole("dialog")).getByRole("status"),
  ).toHaveTextContent(/Saving/);
  fireEvent.click(screen.getByRole("button", { name: "Close" }));
  expect(screen.getByRole("status")).toHaveTextContent(/Saving/);
  await act(async () =>
    held.resolve(
      response({
        ...empty(),
        revision: 1,
        profiles: [profile({ format: "openai-responses" })],
      }),
    ),
  );
});

it("distinguishes a loading read from authoritative empty settings", async () => {
  const read = deferred<Response>();
  const fetcher = vi.fn().mockReturnValue(read.promise);
  vi.stubGlobal("fetch", fetcher);
  render(<AISettingsPage {...props()} />);
  expect(screen.getByRole("status")).toHaveTextContent("Loading AI settings");
  expect(screen.queryByText("No model profiles yet")).not.toBeInTheDocument();
  await act(async () => read.resolve(response(empty())));
  expect(screen.getByRole("heading", { name: "AI settings" })).toBeVisible();
  expect(screen.getByText("No model profiles yet")).toBeVisible();
  expect(screen.getByText(/Never executed/)).toBeVisible();
  expect(fetcher).toHaveBeenCalledWith(
    "/api/v1/ai-settings",
    expect.objectContaining({ method: "GET" }),
  );
});
