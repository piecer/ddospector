// Synthetic worker responses; real strict client and authority hook.
import { afterEach, expect, it, vi } from "vitest";
import {
  act,
  renderHook,
  render,
  fireEvent,
  screen,
  waitFor,
} from "@testing-library/react";
import { toolClient } from "./chat-tool-client";
import { useToolAuthority } from "./useToolAuthority";
import { parseFence, parseTranscript } from "./chat-tool-wire";
import { ChatPanel } from "./ChatPanel";
import {
  runtimeFixture,
  session,
  turn,
  sid,
  response,
} from "./chat-test-fixtures";
import { fence, cid } from "./chat-tool-test-fixtures";
import {
  skillSaved,
  skillTranscript,
  skillRuntime,
  skillInspection,
  draft,
} from "./chat-skill-test-fixtures";
import { skillTemplates } from "./chat-skill-catalog";
const summary = ({
  id,
  name,
  category,
  status,
  version,
}: typeof draft | (typeof skillTemplates)[number]) => ({
  id,
  name,
  category,
  status,
  version,
});
const inventory = {
  schema_version: 1,
  draft_revision: 3,
  skills: [...skillTemplates.map(summary), summary(draft)],
};
const fenced = {
  ...fence,
  generation: 1,
  fenced: true,
  call_ids: [cid],
  current_draft_revision: 3,
};
afterEach(() => vi.unstubAllGlobals());
it("U11 Skill uncertainty reads fence summary fence, optional detail is explicit and closing-revision bound", async () => {
  const fetch = vi.fn(async (u: string) =>
    response(
      u.endsWith("/runtime")
        ? skillRuntime
        : u.endsWith("/skills")
          ? inventory
          : u.endsWith("/skill-test")
            ? skillInspection
            : fenced,
    ),
  );
  vi.stubGlobal("fetch", fetch);
  const { result } = renderHook(() => useToolAuthority(true));
  const record = await parseTranscript({
    ...skillTranscript,
    calls: [
      {
        ...skillSaved,
        status: "uncertain",
        result: null,
        error_code: "CHAT_TOOL_UNCERTAIN",
      },
    ],
  });
  await act(async () => result.current.observe(record));
  await act(async () => {
    await result.current.inspect();
  });
  expect(result.current.review?.skills).toEqual(inventory.skills);
  expect(result.current.review?.calls[0].result).toBeNull();
  expect(result.current.canReconcile).toBe(true);
  expect(fetch.mock.calls.map(([u]) => u).slice(-3)).toEqual([
    "/api/v1/chat/tools/fence",
    "/api/v1/chat/tools/skills",
    "/api/v1/chat/tools/fence",
  ]);
  expect(fetch.mock.calls.some(([u]) => u.includes("skills/"))).toBe(false);
  await act(async () => {
    await result.current.inspectSkill(draft.id);
  });
  expect(result.current.review?.skillDetail).toEqual(draft);
  expect(fetch.mock.calls.map(([u]) => u).slice(-2)).toEqual([
    "/api/v1/chat/tools/skills/skill-test",
    "/api/v1/chat/tools/fence",
  ]);
  expect(result.current.review?.calls[0].status).toBe("uncertain");
});
it.each(["generation", "revision", "ids"])(
  "U11 rejects summary and optional detail %s drift",
  async (kind) => {
    let count = 0;
    const drift = {
      ...fenced,
      ...(kind === "generation"
        ? { generation: 2 }
        : kind === "revision"
          ? { current_draft_revision: 4 }
          : { call_ids: ["77777777-7777-4777-8777-777777777777"] }),
    };
    vi.stubGlobal(
      "fetch",
      vi.fn(async (u: string) => {
        if (u.endsWith("/skills")) return response(inventory);
        if (u.endsWith("/skill-test")) return response(skillInspection);
        return response(++count === 1 ? fenced : drift);
      }),
    );
    await expect(toolClient.inspectSkills()).rejects.toThrow();
    await expect(
      toolClient.inspectSkill(draft.id, parseFence(fenced)),
    ).rejects.toThrow();
  },
);
it("U8 U10 U11 all 103 summaries reachable, duplicate and excess records rejected without details", async () => {
  const custom = Array.from({ length: 100 }, (_, i) => ({
    ...summary(draft),
    id: `custom-${i}`,
    name: { en: "🌍".repeat(120), ko: "🌍".repeat(120) },
  }));
  const value = {
    ...inventory,
    skills: [...skillTemplates.map(summary), ...custom],
  };
  const fetch = vi.fn(async () => response(value));
  vi.stubGlobal("fetch", fetch);
  expect((await toolClient.skills()).skills).toHaveLength(103);
  value.skills.push(custom[0]);
  await expect(toolClient.skills()).rejects.toThrow();
  value.skills.pop();
  value.skills[4] = value.skills[3];
  await expect(toolClient.skills()).rejects.toThrow();
  expect(fetch.mock.calls).toHaveLength(3);
});

it("U11 UI reaches every summary and explicit detail; acknowledgment never relabels uncertain as Saved", async () => {
  const all = {
    ...inventory,
    skills: [
      ...skillTemplates.map(summary),
      ...Array.from({ length: 100 }, (_, i) => ({
        ...summary(draft),
        id: `custom-${i}`,
      })),
    ],
  };
  const fetch = vi.fn(async (u: string, i?: RequestInit) => {
    if (u.endsWith("/tools/runtime")) return response(skillRuntime);
    if (u.endsWith("/runtime")) return response(runtimeFixture);
    if (u.endsWith("/fence")) return response(fenced);
    if (u.endsWith("/skills")) return response(all);
    if (u.endsWith("/custom-99"))
      return response({
        ...skillInspection,
        skill: { ...draft, id: "custom-99" },
      });
    if (u.endsWith("/sessions"))
      return response({
        schema_version: 1,
        sessions: [{ ...session, active_turn_id: null }],
      });
    if (u.endsWith(`/sessions/${sid}`))
      return response({
        schema_version: 1,
        session: { ...session, active_turn_id: null },
        turns: [
          {
            ...turn,
            status: "failed",
            error_code: "CHAT_TOOL_UNCERTAIN",
            transport: "closed",
            provider_stop: "unknown",
            finished_at: turn.created_at,
          },
        ],
        next_before_sequence: null,
      });
    if (u.endsWith("/tools"))
      return response({
        ...skillTranscript,
        calls: [
          {
            ...skillSaved,
            status: "uncertain",
            result: null,
            error_code: "CHAT_TOOL_UNCERTAIN",
          },
        ],
      });
    if (u.endsWith("/reconcile"))
      return response({
        schema_version: 1,
        request_id: JSON.parse(i!.body as string).request_id,
        acknowledged_call_ids: [cid],
        generation: 2,
        write_fenced: false,
        prior_outcomes: "remain_uncertain",
      });
    throw Error("Unexpected synthetic route " + u);
  });
  vi.stubGlobal("fetch", fetch);
  render(<ChatPanel locale="en" />);
  fireEvent.click(await screen.findByTestId(`chat-session-${sid}`));
  await screen.findByTestId(`chat-tool-${cid}`);
  fireEvent.click(screen.getByTestId("chat-tools-reconcile-review"));
  await screen.findByTestId("chat-tools-current-skills");
  expect(
    screen.getAllByRole("button", { name: /Inspect Skill / }),
  ).toHaveLength(103);
  expect(fetch.mock.calls.filter(([u]) => u.includes("/skills/"))).toHaveLength(
    0,
  );
  fireEvent.click(
    screen.getByRole("button", { name: /Inspect Skill custom-99/ }),
  );
  await waitFor(() =>
    expect(screen.getByTestId("chat-tools-skill-detail").textContent).toContain(
      draft.instructions.en,
    ),
  );
  expect(fetch.mock.calls.filter(([u]) => u.includes("/skills/"))).toHaveLength(
    1,
  );
  fireEvent.click(screen.getByTestId("chat-tools-reconcile-confirm"));
  await waitFor(() =>
    expect(
      fetch.mock.calls.filter(([u]) => u.endsWith("/reconcile")),
    ).toHaveLength(1),
  );
  expect(screen.getByTestId(`chat-tool-${cid}`)).toHaveAttribute(
    "data-tool-status",
    "uncertain",
  );
  expect(screen.queryByTestId(`chat-tool-view-saved-${cid}`)).toBeNull();
});
