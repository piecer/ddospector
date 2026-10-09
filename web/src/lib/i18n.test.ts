import { describe, expect, it } from "vitest";
import { choose, text, formatDate } from "./i18n";
describe("locale presentation", () => {
  it("selects Korean without altering original English", () => {
    expect(text({ en: "Evidence", ko: "증거" }, "ko")).toBe("증거");
    expect(text({ en: "Evidence", ko: "증거" }, "en")).toBe("Evidence");
    expect(choose("ko", "Draft", "초안")).toBe("초안");
  });
  it("does not fabricate a date for invalid evidence", () => {
    expect(formatDate("invalid", "en")).toBe("—");
  });
});
