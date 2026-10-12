import { describe, expect, it } from "vitest";
import { decodeResponse, type Context } from "./client";
import { rows, body } from "./testCorpus";
export function context(row: (typeof rows)[number]): Context {
  const u = new URL(row.path, "http://localhost"),
    parts = u.pathname.split("/");
  const kind = u.pathname.endsWith("/events")
    ? "events"
    : u.pathname.endsWith("/cancel")
      ? "cancel"
      : parts[4] === "by-request"
        ? "request"
        : parts.length === 4
          ? row.method === "POST"
            ? "create"
            : "list"
          : "detail";
  return {
    method: row.method as "GET" | "POST",
    status: row.status,
    kind,
    id: kind === "request" ? parts[5] : parts[4],
    after: Number(u.searchParams.get("after") ?? 0),
    limit: Number(u.searchParams.get("limit") ?? (kind === "list" ? 20 : 16)),
    ...(u.searchParams.has("through")
      ? { through: Number(u.searchParams.get("through")) }
      : {}),
  };
}
describe("exact H1 bytes through shipped consumer (earlier source)", () => {
  it.each(
    rows
      .filter((r) => r.path.startsWith("/api/v1/offline-runs"))
      .map((r) => [r.body, r] as const),
  )("HTTP %s", async (_name, row) => {
    const bytes = body(row);
    if (row.status < 300)
      expect(await decodeResponse(bytes, context(row))).toEqual(
        JSON.parse(new TextDecoder().decode(bytes)),
      );
    else
      await expect(decodeResponse(bytes, context(row))).rejects.toMatchObject({
        code: JSON.parse(new TextDecoder().decode(bytes)).code,
      });
  });
});
