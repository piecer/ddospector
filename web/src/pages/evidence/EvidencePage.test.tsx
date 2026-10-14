import { readFileSync } from "node:fs";
import { webcrypto } from "node:crypto";
import { beforeEach, afterEach, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { EvidencePage } from "../operations/EvidencePage";
import { workspaceFixture } from "../../test/fixtures";
import { evidenceAPI } from "./client";
import { runAPI } from "../runs/transport";
import { decodeDetail, decodeList } from "./codec";
import { parseDetail } from "../runs/wire";
const bytes = (n: string) =>
  new Uint8Array(readFileSync("../tests/fixtures/evidence/" + n));
beforeEach(() => {
  Object.defineProperty(globalThis, "crypto", {
    value: webcrypto,
    configurable: true,
  });
  sessionStorage.clear();
});
afterEach(() => vi.restoreAllMocks());
it.each(["en", "ko"] as const)(
  "renders real selected facts, all 16 accessible choices, warnings and explicit two-role form (%s)",
  async (locale) => {
    const fullList = decodeList(bytes("full-list.body"));
    const d = await decodeDetail(bytes("complete-detail.body"));
    // UI-only projection, NOT a genuine producer response: the full-list and
    // complete-detail recordings belong to different repository worlds.
    // Substitute the actual detail summary in its matching ordinal slot;
    // retain the other 15 rows, their order, and the 16-choice view unchanged.
    expect(fullList.total).toBe(16);
    expect(d.evidence.ordinal).toBe(1);
    expect(
      fullList.items.filter((s) => s.ordinal === d.evidence.ordinal),
    ).toHaveLength(1);
    const list = {
      ...fullList,
      items: fullList.items.map((s) =>
        s.ordinal === d.evidence.ordinal ? d.evidence : s,
      ),
    };
    expect(list.items).toHaveLength(list.total);
    expect(new Set(list.items.map((s) => s.id)).size).toBe(16);
    expect(new Set(list.items.map((s) => s.request_id)).size).toBe(16);
    expect(list.items.map((s) => s.ordinal)).toEqual(
      fullList.items.map((s) => s.ordinal),
    );
    list.items.forEach((s, index) =>
      expect(s).toBe(
        s.ordinal === d.evidence.ordinal ? d.evidence : fullList.items[index],
      ),
    );
    const run = await parseDetail(
      JSON.parse(new TextDecoder().decode(bytes("run-before.body"))),
    );
    expect(d.evidence.run_id).toBe(run.run.id);
    expect(d.evidence.run_snapshot_digest).toBe(run.snapshot.digest);
    vi.spyOn(evidenceAPI, "list").mockResolvedValue(list);
    const get = vi.spyOn(evidenceAPI, "get").mockImplementation(async (id) => {
      expect(id).toBe(d.evidence.id);
      return d;
    });
    vi.spyOn(runAPI, "get").mockResolvedValue(run);
    vi.spyOn(runAPI, "list").mockResolvedValue({
      schema_version: 1,
      after: 0,
      through: 1,
      limit: 20,
      total: 1,
      items: [run.run],
      next_after: null,
    });
    const post = vi.spyOn(evidenceAPI, "post");
    const navigate = vi.fn();
    render(
      <EvidencePage
        data={workspaceFixture()}
        locale={locale}
        navigate={navigate}
        refresh={vi.fn()}
      />,
    );
    await waitFor(() =>
      expect(screen.getAllByRole("button", { name: /^#\d+ / })).toHaveLength(
        16,
      ),
    );
    expect(
      screen.getByLabelText(locale === "ko" ? "유입 PCAP" : "Ingress PCAP"),
    ).toHaveAttribute("type", "file");
    expect(
      screen.getByLabelText(locale === "ko" ? "유출 PCAP" : "Egress PCAP"),
    ).toHaveAttribute("type", "file");
    fireEvent.click(screen.getAllByRole("button", { name: /^#\d+ / })[0]);
    expect(
      await screen.findByRole("heading", {
        name:
          locale === "ko"
            ? "SATISFIED · 단일 기준 충족"
            : "SATISFIED · criterion satisfied",
      }),
    ).toBeVisible();
    expect(screen.getByText(/NOT_EVALUATED ·/)).toBeVisible();
    expect(get.mock.calls.map(([id]) => id)).toEqual([d.evidence.id]);
    expect(screen.getAllByRole("button", { name: /^#\d+ / })).toHaveLength(16);
    const selected = screen
      .getByRole("heading", {
        name: locale === "ko" ? "선택된 증거" : "Selected evidence",
      })
      .closest("section")!;
    expect(selected).toHaveTextContent(d.evidence.id);
    expect(selected).toHaveTextContent(
      locale === "ko"
        ? "DUT/서비스/세션 성공이 아닙니다"
        : "not DUT/service/session success",
    );
    expect(
      screen.getAllByText(d.evidence.ingress.sha256).length,
    ).toBeGreaterThan(0);
    expect(
      screen.getByRole("button", {
        name: locale === "ko" ? "JSON 내보내기" : "Export JSON",
      }),
    ).toBeEnabled();
    expect(post).not.toHaveBeenCalled();
  },
);
it("does not call an unavailable repository empty or enable export", async () => {
  vi.spyOn(evidenceAPI, "list").mockRejectedValue(new Error("offline"));
  vi.spyOn(runAPI, "list").mockRejectedValue(new Error("offline"));
  render(
    <EvidencePage
      data={workspaceFixture()}
      locale="en"
      navigate={vi.fn()}
      refresh={vi.fn()}
    />,
  );
  await waitFor(() =>
    expect(screen.getAllByRole("alert").length).toBeGreaterThan(0),
  );
  expect(screen.queryByText("No retained evidence.")).toBeNull();
  expect(screen.queryByRole("button", { name: "Export JSON" })).toBeNull();
});
