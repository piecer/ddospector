import { expect, it } from "vitest";
import { decodeResponse } from "./client";
import { normalWireCases } from "./normalWireFixture";

it.each(normalWireCases)("recorded normal wire: $label", async row => {
  const decode = decodeResponse(Buffer.from(row.raw, "utf8"), row.context);
  if (row.expected === "ACCEPT") await expect(decode).resolves.toBeDefined();
  else await expect(decode).rejects.toThrow("Invalid run response.");
});
