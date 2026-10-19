import { afterEach, expect, it, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { toolClient } from "./chat-tool-client";
import { useToolAuthority } from "./useToolAuthority";
import { response } from "./chat-test-fixtures";
import { fence, cid } from "./chat-tool-test-fixtures";
import {
  inspection,
  targetSaved,
  targetTranscript,
  targetRuntime,
} from "./chat-target-test-fixtures";
import { parseTranscript } from "./chat-tool-wire";
afterEach(() => vi.unstubAllGlobals());
const fenced = {
  ...fence,
  generation: 1,
  fenced: true,
  call_ids: [cid],
  current_draft_revision: 3,
};
it("target uncertainty inspects full current inventory between equal fence observations without inventing an ID", async () => {
  const fetch = vi.fn(async (u: string) =>
    response(
      u.endsWith("/runtime")
        ? targetRuntime
        : u.endsWith("/targets")
          ? inspection
          : fenced,
    ),
  );
  vi.stubGlobal("fetch", fetch);
  const { result } = renderHook(() => useToolAuthority(true));
  const record = await parseTranscript({
    ...targetTranscript,
    calls: [
      {
        ...targetSaved,
        status: "uncertain",
        result: null,
        error_code: "CHAT_TOOL_UNCERTAIN",
      },
    ],
  });
  await act(async () => {
    result.current.observe(record);
  });
  await act(async () => {
    await result.current.inspect();
  });
  expect(result.current.review?.targets).toEqual(inspection.targets);
  expect(result.current.review?.calls[0].result).toBeNull();
  expect(result.current.canReconcile).toBe(true);
  expect(fetch.mock.calls.map(([u]) => u).slice(-3)).toEqual([
    "/api/v1/chat/tools/fence",
    "/api/v1/chat/tools/targets",
    "/api/v1/chat/tools/fence",
  ]);
  expect(fetch.mock.calls.some(([u]) => u.includes("workspace"))).toBe(false);
});
it.each(["generation", "revision", "ids"])(
  "refuses target inspection sandwich drift: %s",
  async (kind) => {
    let count = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (u: string) => {
        if (u.endsWith("/targets")) return response(inspection);
        count++;
        return response(
          count === 1
            ? fenced
            : {
                ...fenced,
                ...(kind === "generation"
                  ? { generation: 2 }
                  : kind === "revision"
                    ? { current_draft_revision: 4 }
                    : { call_ids: ["77777777-7777-4777-8777-777777777777"] }),
              },
        );
      }),
    );
    await expect(toolClient.inspectTargets()).rejects.toThrow();
  },
);
