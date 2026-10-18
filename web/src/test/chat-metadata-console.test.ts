import { describe, expect, it } from "vitest";
import {
  unexpectedConsole,
  type MetadataResponse,
} from "./chat-metadata-console";

const origin = "http://127.0.0.1:5175";
const url = `${origin}/api/v1/chat/runtime`;
const error = {
  url,
  text: "Failed to load resource: the server responded with a status of 429 (Too Many Requests)",
};
const busy: MetadataResponse = {
  order: 1,
  url,
  method: "GET",
  status: 429,
  code: "CHAT_BUSY",
};
const recovered: MetadataResponse = {
  order: 2,
  url,
  method: "GET",
  status: 200,
};

describe("exact recovered metadata console accounting (observer only)", () => {
  it("accounts for one typed same-Origin metadata busy followed by success", () => {
    expect(unexpectedConsole([error], [busy, recovered], origin)).toEqual([]);
  });
  it("never ignores extra duplicate errors or page errors", () => {
    expect(
      unexpectedConsole([error, error], [busy, recovered], origin),
    ).toEqual([error]);
    const pageError = { ...error, url: "" };
    expect(unexpectedConsole([pageError], [busy, recovered], origin)).toEqual([
      pageError,
    ]);
  });
  it.each(
    [
      [],
      [busy],
      [recovered, { ...busy, order: 3 }],
      [{ ...busy, code: "OTHER" }, recovered],
      [{ ...busy, method: "POST" }, recovered],
      [busy, { ...recovered, status: 503 }],
      [busy, { ...recovered, method: "POST" }],
    ].map((responses) => ({ responses })),
  )(
    "rejects missing, unrelated or unrecovered evidence %j",
    ({ responses }) => {
      expect(unexpectedConsole([error], responses, origin)).toEqual([error]);
    },
  );
  it.each([
    "/api/v1/chat/tool-grants",
    "/api/v1/workspace",
    "/api/v1/chat/runtime?x=1",
  ])("does not exempt nonmetadata/query requests %s", (path) => {
    const other = origin + path;
    expect(
      unexpectedConsole(
        [{ ...error, url: other }],
        [
          { ...busy, url: other },
          { ...recovered, url: other },
        ],
        origin,
      ),
    ).toEqual([{ ...error, url: other }]);
  });
  it("rejects a foreign origin and any different console text", () => {
    expect(
      unexpectedConsole([error], [busy, recovered], "http://127.0.0.1:5182"),
    ).toEqual([error]);
    const other = { ...error, text: "unexpected exception" };
    expect(unexpectedConsole([other], [busy, recovered], origin)).toEqual([
      other,
    ]);
  });
});
