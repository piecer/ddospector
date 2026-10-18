import { afterEach, expect, it, vi } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import { useChat } from "./useChat";
import { response, runtimeFixture, session, turn } from "./chat-test-fixtures";
import { grant, textHash } from "./chat-tool-test-fixtures";
afterEach(() => vi.unstubAllGlobals());
it("unknown grant creation recovers by request ID and needs explicit continuation of the captured message", async () => {
  let grantInput: Record<string, unknown> = {},
    grantReadable = false;
  const fetch = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith("/runtime")) return response(runtimeFixture);
    if (url.endsWith("/sessions") && init?.method === "GET")
      return response({ schema_version: 1, sessions: [] });
    if (url.endsWith("/sessions"))
      return response(
        {
          ...session,
          sequence: 0,
          active_turn_id: null,
          request_id: JSON.parse(init!.body as string).request_id,
        },
        201,
      );
    if (url.endsWith("/tool-grants")) {
      grantInput = JSON.parse(init!.body as string);
      throw Error("lost ACK");
    }
    if (url.includes("tool-grants/by-request") && grantReadable)
      return response({
        ...grant,
        request_id: grantInput.request_id,
        turn_request_id: grantInput.turn_request_id,
        text_sha256: textHash(grantInput.text as string),
      });
    if (url.endsWith("/tool-turns"))
      return response(
        {
          ...turn,
          request_id: grantInput.turn_request_id,
          user_text: grantInput.text,
        },
        202,
      );
    throw Error("not yet readable");
  });
  vi.stubGlobal("fetch", fetch);
  const { result } = renderHook(() => useChat("en", true, true));
  await waitFor(() => expect(result.current.runtime?.supported).toBe(true));
  await act(async () => {
    await result.current.start();
  });
  act(() => result.current.setInput("exact first message"));
  await act(async () => {
    await result.current.send(true);
  });
  expect(result.current.phase).toBe("unknown-send");
  expect(result.current.busy).toBe(false);
  act(() => result.current.setInput("edited later, not approved"));
  grantReadable = true;
  await act(async () => {
    await result.current.recoverSubmission();
  });
  expect(
    fetch.mock.calls.filter(([url]) => url.endsWith("/tool-turns")),
  ).toHaveLength(0);
  expect(result.current.phase).toBe("grant-recovered");
  await act(async () => {
    await (
      result.current as unknown as { continueGrant(): Promise<void> }
    ).continueGrant();
  });
  expect(
    JSON.parse(
      fetch.mock.calls.find(([url]) => url.endsWith("/tool-turns"))![1]!
        .body as string,
    ).text,
  ).toBe("exact first message");
  expect(result.current.input).toBe("edited later, not approved");
  expect(
    fetch.mock.calls.filter(([url]) => url.endsWith("/tool-grants")),
  ).toHaveLength(1);
});
it("workspace unavailable while grant ACK is pending prevents tool admission but retires request ownership", async () => {
  let release: (r: Response) => void = () => undefined,
    captured: Record<string, unknown> = {};
  const fetch = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith("/runtime")) return response(runtimeFixture);
    if (url.endsWith("/sessions") && init?.method === "GET")
      return response({ schema_version: 1, sessions: [] });
    if (url.endsWith("/sessions"))
      return response(
        {
          ...session,
          sequence: 0,
          active_turn_id: null,
          request_id: JSON.parse(init!.body as string).request_id,
        },
        201,
      );
    if (url.endsWith("/tool-grants")) {
      captured = JSON.parse(init!.body as string);
      return new Promise<Response>((r) => {
        release = r;
      });
    }
    throw Error("Unexpected");
  });
  vi.stubGlobal("fetch", fetch);
  const { result, rerender } = renderHook(
    ({ enabled }) => useChat("en", enabled, enabled),
    { initialProps: { enabled: true } },
  );
  await waitFor(() => expect(result.current.runtime?.supported).toBe(true));
  await act(async () => {
    await result.current.start();
  });
  act(() => result.current.setInput("hello"));
  let send: Promise<void>;
  act(() => {
    send = result.current.send(true);
  });
  rerender({ enabled: false });
  await act(async () => {
    release(
      response(
        {
          ...grant,
          request_id: captured.request_id,
          turn_request_id: captured.turn_request_id,
        },
        201,
      ),
    );
    await send;
  });
  expect(
    fetch.mock.calls.filter(([url]) => url.endsWith("/tool-turns")),
  ).toHaveLength(0);
  expect(result.current.busy).toBe(false);
  expect(result.current.uncertain).toBe(true);
});
