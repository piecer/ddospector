import { readFileSync } from "node:fs";
import { webcrypto } from "node:crypto";
import { beforeAll, afterEach, expect, it, vi } from "vitest";
import { exportReport, download, boundedText } from "./export";
import { decodeDetail } from "./codec";
import { parseDetail } from "../runs/wire";
const text = (n: string) =>
  readFileSync("../tests/fixtures/evidence/" + n, "utf8");
beforeAll(() =>
  Object.defineProperty(globalThis, "crypto", {
    value: webcrypto,
    configurable: true,
  }),
);
afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});
it("exports canonical facts identically in both locales and standalone escaped bounded HTML", async () => {
  const d = await decodeDetail(
      new TextEncoder().encode(text("complete-detail.body")),
    ),
    r = await parseDetail(JSON.parse(text("run-before.body")));
  const en = await exportReport(d, r, "en"),
    ko = await exportReport(d, r, "ko");
  expect(en.json).toBe(ko.json);
  for (const e of [en, ko]) {
    expect(new TextEncoder().encode(e.json).length).toBeLessThanOrEqual(65536);
    expect(new TextEncoder().encode(e.html).length).toBeLessThanOrEqual(131072);
    expect(e.html).toContain("default-src");
    expect(e.html).not.toContain("<script");
    expect(e.html).toContain("NOT_EVALUATED");
    expect(e.html).toContain("SYNTHETIC");
  }
  expect(en.html).toContain("Producer start time");
  expect(ko.html).toContain("생산자 시작 시각");
  const hostile = JSON.parse(text("complete-detail.body"));
  hostile.evidence.ingress.name = "<img src=x onerror=alert(1)>";
  const escaped = await exportReport(hostile, r, "en");
  expect(escaped.html).toContain("&lt;img");
  expect(escaped.html).not.toContain("<img");
});
it("refuses unassessed/corrupt/foreign reports and exact/+1 export budgets", async () => {
  const r = await parseDetail(JSON.parse(text("run-before.body"))),
    d = JSON.parse(text("complete-detail.body"));
  await expect(exportReport(d, r, '"><script>' as "en")).rejects.toThrow();
  d.report.digest = "0".repeat(64);
  await expect(exportReport(d, r, "en")).rejects.toThrow();
  await expect(
    exportReport(
      await decodeDetail(
        new TextEncoder().encode(text("complete-registered.body")),
      ),
      r,
      "en",
    ),
  ).rejects.toThrow();
  for (const max of [65536, 131072]) {
    expect(boundedText("x".repeat(max), max).length).toBe(max);
    expect(() => boundedText("x".repeat(max + 1), max)).toThrow();
  }
});
it("retires an object URL immediately if the browser refuses the download click", () => {
  Object.defineProperty(URL, "createObjectURL", {
    value: vi.fn(() => "blob:failed"),
    configurable: true,
  });
  Object.defineProperty(URL, "revokeObjectURL", {
    value: vi.fn(),
    configurable: true,
  });
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {
    throw new Error("blocked");
  });
  expect(() => download("x", "application/json", "evidence.json")).toThrow();
  expect(URL.revokeObjectURL).toHaveBeenCalledExactlyOnceWith("blob:failed");
  expect(document.querySelector("a[download]")).toBeNull();
});
it("retires every object URL and removes transient anchors", () => {
  vi.useFakeTimers();
  Object.defineProperty(URL, "createObjectURL", {
    value: vi.fn(() => "blob:owned"),
    configurable: true,
  });
  Object.defineProperty(URL, "revokeObjectURL", {
    value: vi.fn(),
    configurable: true,
  });
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
  const retire = download("x", "application/json", "evidence.json");
  expect(URL.createObjectURL).toHaveBeenCalledTimes(1);
  expect(document.querySelector("a[download]")).toBeNull();
  retire();
  vi.runAllTimers();
  expect(URL.revokeObjectURL).toHaveBeenCalledExactlyOnceWith("blob:owned");
});
