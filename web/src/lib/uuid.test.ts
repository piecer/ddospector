import { afterEach, expect, it, vi } from "vitest";
import { newProfile } from "../pages/ai-settings/ProfileEditor";

afterEach(() => vi.unstubAllGlobals());

it("creates a profile on HTTP without native randomUUID", () => {
  const getRandomValues = vi.fn((bytes: Uint8Array) => {
    bytes.fill(0xff);
    return bytes;
  });
  vi.stubGlobal("crypto", { getRandomValues });
  expect(newProfile().id).toBe("llm-ffffffff-ffff-4fff-bfff-ffffffffffff");
  expect(getRandomValues).toHaveBeenCalledOnce();
});


it("delegates to native randomUUID when available", () => {
  const native = vi.fn(() => "00000000-0000-4000-8000-000000000000");
  const source = { randomUUID: native, getRandomValues: vi.fn() };
  vi.stubGlobal("crypto", source);
  expect(newProfile().id).toBe("llm-00000000-0000-4000-8000-000000000000");
  expect(native).toHaveBeenCalledOnce();
  expect(source.getRandomValues).not.toHaveBeenCalled();
  expect(globalThis.crypto).toBe(source);
});

it("never substitutes weak randomness when crypto is unavailable", () => {
  vi.stubGlobal("crypto", undefined);
  expect(() => newProfile()).toThrow("Secure random number generation is unavailable.");
});

it("preserves all random bits except UUID version and variant", () => {
  const source = { getRandomValues: vi.fn((bytes: Uint8Array) => {
    bytes.set(Array.from({ length: 16 }, (_, i) => i));
    return bytes;
  }) };
  vi.stubGlobal("crypto", source);
  expect(newProfile().id).toBe("llm-00010203-0405-4607-8809-0a0b0c0d0e0f");
  expect(source).not.toHaveProperty("randomUUID");
});
