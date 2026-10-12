import { describe, expect, it } from "vitest";
import { rawJSON } from "./raw";
import { parseDetail } from "./wire";
import { rows, body } from "./testCorpus";
describe("preliminary actual H1 HTTP bytes, not final backend acceptance", () => {
  it.each(
    rows.filter((r) => r.state !== null).map((r) => [r.body, r] as const),
  )("validates actual state/result witness %s", async (_name, row) => {
    const value = rawJSON(body(row), 32768);
    expect(await parseDetail(value)).toEqual(value);
  });
  it("rejects hidden result descriptors without running getters or toJSON", async () => {
    const row = rows.find((r) => r.state === "SUCCEEDED")!;
    for (const mode of ["getter", "symbol", "hidden", "prototype"]) {
      const value = rawJSON(body(row), 32768) as {
        result: Record<string, unknown>;
      };
      let calls = 0;
      if (mode === "getter")
        Object.defineProperty(value.result, "evaluation", {
          enumerable: true,
          get() {
            calls++;
            return "NOT_EVALUATED";
          },
        });
      if (mode === "symbol")
        Object.defineProperty(value.result, Symbol("hidden"), { value: null });
      if (mode === "hidden")
        Object.defineProperty(value.result, "toJSON", {
          value: () => {
            calls++;
            return null;
          },
        });
      if (mode === "prototype")
        Object.setPrototypeOf(value.result, { secret: true });
      await expect(parseDetail(value)).rejects.toThrow();
      expect(calls).toBe(0);
    }
  });
  it("accepts a real queued captured Detail without inventing result or telemetry", async () => {
    const row = rows.find((r) => r.state === "QUEUED")!;
    const value = rawJSON(body(row), 32768);
    expect(await parseDetail(value)).toEqual(value);
  });
});
