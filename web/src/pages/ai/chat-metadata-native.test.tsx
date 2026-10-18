import { spawn } from "node:child_process";
import { createInterface } from "node:readline";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { useChat } from "./useChat";
import { response } from "./chat-test-fixtures";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("recovers after a cancelled native observer retires, without queueing or early metadata authority", async () => {
  const directory = dirname(fileURLToPath(import.meta.url));
  const root = resolve(directory, "../../../..");
  const child = spawn(
    resolve(root, ".venv/bin/python"),
    [resolve(directory, "chat-metadata-native-probe.py")],
    { env: { ...process.env, PYTHONPATH: resolve(root, "src") } },
  );
  const lines = createInterface({ input: child.stdout });
  const replies = lines[Symbol.asyncIterator]();
  let stderr = "";
  child.stderr.on("data", (chunk) => {
    stderr += String(chunk);
  });
  const exited = new Promise<number | null>((done) => child.once("exit", done));
  const next = async () => {
    const line = await replies.next();
    if (line.done) throw Error(`Native probe ended: ${stderr}`);
    return JSON.parse(line.value);
  };
  const command = async (value: string) => {
    child.stdin.write(JSON.stringify(value) + "\n");
    return next();
  };
  const starts: number[] = [],
    completions: number[] = [];
  let calls = 0;
  try {
    expect(await next()).toMatchObject({ held_after_cancel: true });
    const fetch = vi.fn(async (url: string, init?: RequestInit) => {
      expect(init?.method).toBe("GET");
      if (url.endsWith("/sessions"))
        return response({ schema_version: 1, sessions: [] });
      expect(url).toBe("/api/v1/chat/runtime");
      starts.push(performance.now());
      const result = await command("runtime");
      completions.push(performance.now());
      ++calls;
      return response(result.body, result.status);
    });
    vi.stubGlobal("fetch", fetch);
    const { result, unmount } = renderHook(() => useChat("en", true));
    await waitFor(() => expect(calls).toBe(1));
    expect(result.current.runtime).toBeNull();
    expect(await command("release")).toEqual({ retired: true });
    await waitFor(() => expect(result.current.phase).toBe("ready"), {
      timeout: 2000,
    });
    expect(result.current.runtime).not.toBeNull();
    expect(calls).toBe(2);
    expect(starts[1] - completions[0]).toBeGreaterThanOrEqual(500);
    await act(async () => unmount());
  } finally {
    child.stdin.write('"close"\n');
    child.stdin.end();
    expect(await exited).toBe(0);
    expect(stderr).toBe("");
    lines.close();
  }
}, 10000);
