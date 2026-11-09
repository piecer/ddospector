import { createHash } from "node:crypto";
import { afterEach, expect, it, vi } from "vitest";
import { canonical, digest } from "../pages/scenarios/json";
import { hashBytes } from "../pages/evidence/client";
import { sha256 } from "./sha256";

afterEach(() => vi.unstubAllGlobals());

it.each([0, 1, 55, 56, 63, 64, 65, 127, 128, 65536, 1048583])(
  "matches Node SHA-256 for %i binary bytes on HTTP",
  async (length) => {
    vi.stubGlobal("crypto", {});
    const bytes = Uint8Array.from({ length }, (_, i) => (i * 37 + 129) & 255);
    const before = bytes.slice();
    expect(await sha256(bytes)).toBe(createHash("sha256").update(bytes).digest("hex"));
    expect(bytes).toEqual(before);
  },
);

it("snapshots input before yielding and does not block a whole large digest", async () => {
  vi.stubGlobal("crypto", {});
  const bytes = new Uint8Array(1048583).fill(123);
  const expected = createHash("sha256").update(bytes).digest("hex");
  const hashing = sha256(bytes);
  bytes.fill(0);
  expect(await hashing).toBe(expected);
});

it("keeps native digest failures rather than silently falling back", async () => {
  const error = new Error("native digest failure");
  const native = vi.fn().mockRejectedValue(error);
  vi.stubGlobal("crypto", { subtle: { digest: native } });
  await expect(sha256(new Uint8Array([1]))).rejects.toBe(error);
  expect(native).toHaveBeenCalledOnce();
});

it("preserves scenario and evidence SHA-256 without secure-context subtle", async () => {
  vi.stubGlobal("crypto", {});
  const value = { name: "개발 LAN", entries: [1, true, "x"] };
  expect(await digest(value)).toBe(createHash("sha256").update(canonical(value)).digest("hex"));
  const bytes = new Uint8Array([0, 255, 1, 128]);
  expect(await hashBytes(bytes)).toBe(createHash("sha256").update(bytes).digest("hex"));
});
