import { afterEach, describe, expect, it, vi } from "vitest";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ComponentType } from "react";
import type { PageProps, WorkspaceSnapshot } from "../../lib/contracts";
import { api } from "../../lib/api";
import { workspaceFixture } from "../../test/fixtures";

import * as pages from "./index";

function page(name: string): ComponentType<PageProps> {
  return pages[name as keyof typeof pages];
}
function props(
  data = workspaceFixture(),
  locale: PageProps["locale"] = "en",
): PageProps {
  return {
    data,
    locale,
    navigate: vi.fn(),
    refresh: vi.fn().mockResolvedValue(undefined),
  };
}
function readyWorkspace(): WorkspaceSnapshot {
  const data = workspaceFixture();
  data.targets = [
    {
      id: "target-1",
      name: "Lab firewall",
      address: "192.0.2.10",
      kind: "DUT",
      status: "draft",
      created_at: "2026-10-09T00:00:00Z",
    },
  ];
  data.profiles = [
    {
      id: "profile-1",
      name: { en: "Policy replay", ko: "정책 재생" },
      description: { en: "A test template", ko: "테스트 템플릿" },
      engine: "tcpreplay",
      layer: "L3",
      status: "template",
    },
  ];
  return data;
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("CampaignsPage", () => {
  it("explains missing prerequisites and routes to target setup without creating a draft", async () => {
    const input = props();
    const create = vi.spyOn(api, "createCampaign");
    const CampaignsPage = page("CampaignsPage");
    render(<CampaignsPage {...input} />);
    expect(
      screen.getByRole("heading", { level: 1, name: "Campaigns" }),
    ).toBeVisible();
    expect(screen.getByRole("button", { name: "New campaign" })).toBeDisabled();
    expect(
      screen.getByText(
        "Add a target draft and a profile template before creating a campaign.",
      ),
    ).toBeVisible();
    await userEvent.click(
      screen.getByRole("button", { name: "Configure targets" }),
    );
    expect(input.navigate).toHaveBeenCalledWith("targets");
    expect(create).not.toHaveBeenCalled();
    expect(
      screen.getByRole("heading", { name: "No campaign drafts yet" }),
    ).toBeVisible();
  });
});

describe("campaign draft creation", () => {
  it("submits only a validated draft through the real API client, awaits it and refreshes server data", async () => {
    const input = props(readyWorkspace());
    let finish!: (value: Response) => void;
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    const CampaignsPage = page("CampaignsPage");
    render(<CampaignsPage {...input} />);
    await userEvent.click(screen.getByRole("button", { name: "New campaign" }));
    const dialog = screen.getByRole("dialog", { name: "New campaign draft" });
    await userEvent.type(
      within(dialog).getByLabelText("Campaign name"),
      "  Firewall review  ",
    );
    await userEvent.type(
      within(dialog).getByLabelText("Objective"),
      "  Verify the lab policy  ",
    );
    await userEvent.selectOptions(
      within(dialog).getByLabelText("Target"),
      "target-1",
    );
    await userEvent.selectOptions(
      within(dialog).getByLabelText("Profile template"),
      "profile-1",
    );
    await userEvent.click(
      within(dialog).getByRole("button", { name: "Save draft" }),
    );
    expect(fetchMock).toHaveBeenCalledOnce();
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/campaigns",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          name: "Firewall review",
          objective: "Verify the lab policy",
          target_id: "target-1",
          profile_id: "profile-1",
        }),
      }),
    );
    expect(
      within(dialog).getByRole("button", { name: "Saving draft…" }),
    ).toBeDisabled();
    expect(input.refresh).not.toHaveBeenCalled();
    finish(
      new Response(
        JSON.stringify({
          id: "campaign-1",
          name: "Firewall review",
          objective: "Verify the lab policy",
          target_id: "target-1",
          profile_id: "profile-1",
          status: "draft",
          created_at: "2026-10-09T00:00:00Z",
        }),
        { status: 201 },
      ),
    );
    await waitFor(() => expect(input.refresh).toHaveBeenCalledOnce());
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
    expect(screen.getByRole("status")).toHaveTextContent(
      "Campaign draft saved. No execution was started.",
    );
    expect(
      screen.getByRole("heading", { name: "No campaign drafts yet" }),
    ).toBeVisible();
  });
});

describe("persisted campaign inspection", () => {
  it.each(["en", "ko"] as const)(
    "renders only supplied drafts with real references and an inspectable objective (%s)",
    async (locale) => {
      const data = readyWorkspace();
      data.campaigns = [
        {
          id: "campaign-real",
          name: "실제 초안",
          objective: "<script>not markup</script>",
          target_id: "target-1",
          profile_id: "profile-1",
          status: "draft",
          created_at: "2026-10-09T00:00:00Z",
        },
      ];
      const CampaignsPage = page("CampaignsPage");
      render(<CampaignsPage {...props(data, locale)} />);
      const table = screen.getByRole("region", {
        name: locale === "ko" ? "캠페인 초안 목록" : "Campaign draft list",
      });
      expect(table).toHaveAttribute("tabindex", "0");
      expect(within(table).getAllByRole("row")).toHaveLength(2);
      expect(within(table).getByText("Lab firewall")).toBeVisible();
      expect(
        within(table).getByText(
          locale === "ko" ? "정책 재생" : "Policy replay",
        ),
      ).toBeVisible();
      await userEvent.click(
        within(table).getByRole("button", { name: "실제 초안" }),
      );
      const dialog = screen.getByRole("dialog", {
        name: locale === "ko" ? "캠페인 초안 상세" : "Campaign draft details",
      });
      expect(
        within(dialog).getByText("<script>not markup</script>"),
      ).toBeVisible();
      expect(within(dialog).getByText("campaign-real")).toBeVisible();
      expect(
        within(dialog).getByRole("button", {
          name: locale === "ko" ? "실행 시작" : "Start run",
        }),
      ).toBeDisabled();
      expect(
        within(dialog).getByText(
          locale === "ko"
            ? "이 초안은 실행을 승인하지 않습니다. 서버에서 라이브 실행을 허용하지 않습니다."
            : "This draft grants no execution authority. The server does not allow live runs.",
        ),
      ).toBeVisible();
      expect(dialog.querySelector("script")).toBeNull();
    },
  );
});

async function fillCampaign() {
  await userEvent.click(screen.getByRole("button", { name: "New campaign" }));
  const dialog = screen.getByRole("dialog", { name: "New campaign draft" });
  fireEvent.change(within(dialog).getByLabelText("Campaign name"), {
    target: { value: "Review policy" },
  });
  fireEvent.change(within(dialog).getByLabelText("Objective"), {
    target: { value: "A bounded lab review" },
  });
  await userEvent.selectOptions(
    within(dialog).getByLabelText("Target"),
    "target-1",
  );
  await userEvent.selectOptions(
    within(dialog).getByLabelText("Profile template"),
    "profile-1",
  );
  return dialog;
}

describe("campaign recovery", () => {
  it("keeps the draft editable when the API rejects saving and permits a retry", async () => {
    const input = props(readyWorkspace());
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(
        new Response(JSON.stringify({ message: "Draft rejected" }), {
          status: 409,
        }),
      );
    const CampaignsPage = page("CampaignsPage");
    render(<CampaignsPage {...input} />);
    const dialog = await fillCampaign();
    await userEvent.click(
      within(dialog).getByRole("button", { name: "Save draft" }),
    );
    expect(await within(dialog).findByRole("alert")).toHaveTextContent(
      "The draft could not be saved. Your input is preserved; check the workspace and try again.",
    );
    expect(within(dialog).getByLabelText("Campaign name")).toHaveValue(
      "Review policy",
    );
    expect(
      within(dialog).getByRole("button", { name: "Save draft" }),
    ).toBeEnabled();
    expect(input.refresh).not.toHaveBeenCalled();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledOnce();
  });

  it("distinguishes a committed draft from a failed refresh without inviting duplicate submission", async () => {
    const input = props(readyWorkspace());
    const create = vi
      .spyOn(api, "createCampaign")
      .mockResolvedValue({
        id: "created",
        name: "Review policy",
        objective: "A bounded lab review",
        target_id: "target-1",
        profile_id: "profile-1",
        status: "draft",
        created_at: "",
      });
    vi.mocked(input.refresh)
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValue(undefined);
    const CampaignsPage = page("CampaignsPage");
    render(<CampaignsPage {...input} />);
    const dialog = await fillCampaign();
    await userEvent.click(
      within(dialog).getByRole("button", { name: "Save draft" }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The draft was saved, but the list could not be refreshed. Refresh the list before creating another draft.",
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "New campaign" })).toBeDisabled();
    await userEvent.click(
      screen.getByRole("button", { name: "Retry refresh" }),
    );
    await waitFor(() =>
      expect(screen.queryByRole("alert")).not.toBeInTheDocument(),
    );
    expect(screen.getByRole("button", { name: "New campaign" })).toBeEnabled();
    expect(create).toHaveBeenCalledOnce();
    expect(input.refresh).toHaveBeenCalledTimes(2);
  });

  it("explains the local 100-draft limit and disables further creation", () => {
    const data = readyWorkspace();
    data.campaigns = Array.from({ length: 100 }, (_, index) => ({
      id: `c-${index}`,
      name: `Draft ${index}`,
      objective: "Test objective",
      target_id: "target-1",
      profile_id: "profile-1",
      status: "draft" as const,
      created_at: "",
    }));
    const CampaignsPage = page("CampaignsPage");
    render(<CampaignsPage {...props(data)} />);
    expect(screen.getByRole("button", { name: "New campaign" })).toBeDisabled();
    expect(
      screen.getByText(
        "The local limit of 100 campaign drafts has been reached. Additional drafts cannot be saved.",
      ),
    ).toBeVisible();
  });
});

describe("RunsPage", () => {
  it.each(["en", "ko"] as const)(
    "reads real OFFLINE history separately while retaining LIVE denial and no fabricated telemetry (%s)",
    async (locale) => {
      const input = props(workspaceFixture(), locale);
      vi.spyOn(globalThis, "fetch").mockImplementation(async (url) => new Response(JSON.stringify(
        String(url).startsWith("/api/v1/offline-runs?")
          ? {schema_version:1,after:0,through:0,limit:20,total:0,items:[],next_after:null}
          : {revision:0,total:0,offset:0,limit:20,items:[],execution_enabled:false}
      )));
      const RunsPage = page("RunsPage");
      render(<RunsPage {...input} />);
      expect(screen.getByRole("heading", {level:1,name:locale==="ko"?"실행":"Runs"})).toBeVisible();
      expect(await screen.findByRole("heading", {name:locale==="ko"?"아직 OFFLINE 실행 없음":"No OFFLINE runs yet"})).toBeVisible();
      const reason=locale==="ko"?"서버에서 라이브 실행이 비활성화되어 있습니다. 캠페인 초안은 실행되지 않습니다.":"Live execution is disabled on the server. Campaign drafts do not start runs.";
      const live=screen.getByRole("button", {name:locale==="ko"?"실행 시작":"Start run"});
      expect(live).toBeDisabled();expect(live).toHaveAccessibleDescription(reason);
      expect(screen.getByRole("button", {name:locale==="ko"?"OFFLINE 준비 시작":"Start OFFLINE preparation"})).toBeDisabled();
      expect(screen.getByText("NOT_EVALUATED")).toBeVisible();
      expect(screen.getByText(locale==="ko"?"측정값과 방어 판정은 null입니다. 캡처 패킷이나 장비 증거를 가져오지 않았습니다.":"Measurements and defense verdict remain null. No captured packets or device evidence have been ingested.")).toBeVisible();
      await userEvent.click(await screen.findByRole("button", {name:locale==="ko"?"시나리오 라이브러리 열기":"Open scenario library"}));
      expect(input.navigate).toHaveBeenCalledWith("profiles");
      expect(screen.queryByRole("table")).not.toBeInTheDocument();
      expect(vi.mocked(globalThis.fetch).mock.calls.every(([,options])=>options?.method==="GET")).toBe(true);
    },
  );
});

describe("FindingsPage", () => {
  it.each(["en", "ko"] as const)(
    "distinguishes no evidence from a clean security result (%s)",
    async (locale) => {
      const input = props(workspaceFixture(), locale);
      const FindingsPage = page("FindingsPage");
      render(<FindingsPage {...input} />);
      expect(
        screen.getByRole("heading", {
          level: 1,
          name: locale === "ko" ? "발견 사항" : "Findings",
        }),
      ).toBeVisible();
      expect(
        screen.getByRole("heading", {
          name:
            locale === "ko"
              ? "검토할 발견 사항이 없습니다"
              : "No findings to review",
        }),
      ).toBeVisible();
      const reason =
        locale === "ko"
          ? "실행 증거가 없어 분석할 수 없습니다. 발견 사항이 없다는 것은 검증을 통과했다는 뜻이 아닙니다."
          : "Analysis requires run evidence. An empty list does not mean validation passed.";
      expect(
        screen.getByRole("button", {
          name: locale === "ko" ? "증거 분석" : "Analyze evidence",
        }),
      ).toBeDisabled();
      expect(
        screen.getByRole("button", {
          name: locale === "ko" ? "증거 분석" : "Analyze evidence",
        }),
      ).toHaveAccessibleDescription(reason);
      expect(
        screen.getByRole("heading", {
          name: locale === "ko" ? "검토 기준" : "Review criteria",
        }),
      ).toBeVisible();
      expect(
        screen.getByText(
          locale === "ko"
            ? "심각도는 평가되지 않았습니다."
            : "Severity has not been assessed.",
        ),
      ).toBeVisible();
      await userEvent.click(
        screen.getByRole("button", {
          name:
            locale === "ko"
              ? "증거 워크스페이스 열기"
              : "Open evidence workspace",
        }),
      );
      expect(input.navigate).toHaveBeenCalledWith("evidence");
    },
  );
});

describe("EvidencePage", () => {
  it.each(["en", "ko"] as const)(
    "presents artifact requirements without claiming files or generated bundles (%s)",
    async (locale) => {
      const input = props(workspaceFixture(), locale);
      const EvidencePage = page("EvidencePage");
      render(<EvidencePage {...input} />);
      expect(
        screen.getByRole("heading", {
          level: 1,
          name: locale === "ko" ? "증거" : "Evidence",
        }),
      ).toBeVisible();
      expect(
        screen.getByRole("heading", {
          name:
            locale === "ko"
              ? "수집된 자료가 없습니다"
              : "No artifacts collected",
        }),
      ).toBeVisible();
      expect(
        screen.getByRole("button", {
          name:
            locale === "ko" ? "증거 묶음 내보내기" : "Export evidence bundle",
        }),
      ).toBeDisabled();
      expect(
        screen.getByRole("button", {
          name:
            locale === "ko" ? "증거 묶음 내보내기" : "Export evidence bundle",
        }),
      ).toHaveAccessibleDescription(
        locale === "ko"
          ? "보관된 실행 자료가 없으며 증거 내보내기는 아직 구현되지 않았습니다."
          : "There are no retained run artifacts, and evidence export is not implemented.",
      );
      expect(
        screen.getByRole("heading", {
          name:
            locale === "ko"
              ? "출처 및 무결성 요건"
              : "Provenance & integrity requirements",
        }),
      ).toBeVisible();
      expect(
        screen.getByText(
          locale === "ko"
            ? "로컬 초안은 실행 증거가 아닙니다."
            : "Local drafts are not execution evidence.",
        ),
      ).toBeVisible();
      await userEvent.click(
        screen.getByRole("button", {
          name:
            locale === "ko" ? "실행 워크스페이스 열기" : "Open run workspace",
        }),
      );
      expect(input.navigate).toHaveBeenCalledWith("runs");
      await userEvent.click(
        screen.getByRole("button", {
          name:
            locale === "ko"
              ? "초안 감사 이력 보기"
              : "View draft audit history",
        }),
      );
      expect(input.navigate).toHaveBeenCalledWith("audit");
    },
  );
});

describe("ApprovalsPage", () => {
  it.each(["en", "ko"] as const)(
    "shows review-only authority without granting operational approval (%s)",
    async (locale) => {
      const data = workspaceFixture();
      data.agent_profile.name = "Local review agent";
      const input = props(data, locale);
      const ApprovalsPage = page("ApprovalsPage");
      render(<ApprovalsPage {...input} />);
      expect(
        screen.getByRole("heading", {
          level: 1,
          name: locale === "ko" ? "승인" : "Approvals",
        }),
      ).toBeVisible();
      expect(
        screen.getByRole("heading", {
          name:
            locale === "ko"
              ? "운영 승인 요청이 없습니다"
              : "No operational approval requests",
        }),
      ).toBeVisible();
      expect(screen.getByText("Local review agent")).toBeVisible();
      expect(screen.getByText("REVIEW_ONLY")).toBeVisible();
      const button = screen.getByRole("button", {
        name: locale === "ko" ? "실행 승인" : "Approve execution",
      });
      expect(button).toBeDisabled();
      expect(button).toHaveAccessibleDescription(
        locale === "ko"
          ? "운영 승인과 안전 게이트가 아직 구현되지 않았습니다. 이 화면에서는 권한을 부여할 수 없습니다."
          : "Operational approval and the safety gate are not implemented. This page cannot grant authority.",
      );
      const table = screen.getByRole("region", {
        name:
          locale === "ko" ? "현재 기능 경계" : "Current capability boundaries",
      });
      expect(
        within(table)
          .getByText(locale === "ko" ? "라이브 실행" : "Live execution")
          .closest("tr"),
      ).toHaveTextContent(locale === "ko" ? "비활성" : "Disabled");
      await userEvent.click(
        screen.getByRole("button", {
          name: locale === "ko" ? "에이전트 정책 검토" : "Review agent policy",
        }),
      );
      expect(input.navigate).toHaveBeenCalledWith("agent");
    },
  );
});

describe("AuditPage", () => {
  it.each(["en", "ko"] as const)(
    "renders actual draft events newest first and exposes their exact identifiers (%s)",
    async (locale) => {
      const data = workspaceFixture();
      data.audit = [
        {
          id: "event-old",
          action: "target.created",
          entity_id: "target-real",
          created_at: "2026-10-08T01:00:00Z",
          origin: "local_operator",
        },
        {
          id: "event-new",
          action: "campaign.created",
          entity_id: "campaign-real",
          created_at: "2026-10-09T02:00:00Z",
          origin: "local_operator",
        },
      ];
      const AuditPage = page("AuditPage");
      render(<AuditPage {...props(data, locale)} />);
      expect(
        screen.getByRole("heading", {
          level: 1,
          name: locale === "ko" ? "감사 이력" : "Audit log",
        }),
      ).toBeVisible();
      const table = screen.getByRole("region", {
        name:
          locale === "ko"
            ? "로컬 초안 감사 이벤트"
            : "Local draft audit events",
      });
      expect(table).toHaveAttribute("tabindex", "0");
      const rows = within(table).getAllByRole("row");
      expect(rows).toHaveLength(3);
      expect(rows[1]).toHaveTextContent("campaign.created");
      expect(rows[2]).toHaveTextContent("target.created");
      expect(data.audit[0].id).toBe("event-old");
      await userEvent.click(
        within(rows[1]).getByRole("button", { name: "event-new" }),
      );
      const dialog = screen.getByRole("dialog", {
        name: locale === "ko" ? "감사 이벤트 상세" : "Audit event details",
      });
      expect(within(dialog).getByText("campaign-real")).toBeVisible();
      expect(within(dialog).getByText("2026-10-09T02:00:00Z")).toBeVisible();
      expect(within(dialog).getByText("local_operator")).toBeVisible();
      expect(
        screen.getByText(
          locale === "ko"
            ? "현재 스냅샷의 이벤트만 표시합니다. 전체 기간 이력이나 변조 방지 감사 저장소가 아닙니다."
            : "Only events in the current snapshot are shown. This is not a lifetime history or a tamper-proof audit store.",
        ),
      ).toBeVisible();
    },
  );

  it("does not invent history for an untouched workspace", async () => {
    const input = props();
    const AuditPage = page("AuditPage");
    render(<AuditPage {...input} />);
    expect(
      screen.getByRole("heading", { name: "No draft activity recorded" }),
    ).toBeVisible();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    await userEvent.click(
      screen.getByRole("button", { name: "Configure the workspace" }),
    );
    expect(input.navigate).toHaveBeenCalledWith("targets");
  });
});

describe("audit search", () => {
  it("filters the supplied snapshot by exact data fields and distinguishes no matches from no activity", async () => {
    const data = workspaceFixture();
    data.audit = [
      {
        id: "evt-1",
        action: "target.created",
        entity_id: "device-a",
        created_at: "",
        origin: "local_operator",
      },
      {
        id: "evt-2",
        action: "campaign.created",
        entity_id: "campaign-b",
        created_at: "",
        origin: "local_operator",
      },
    ];
    const AuditPage = page("AuditPage");
    render(<AuditPage {...props(data)} />);
    const search = screen.getByRole("searchbox", {
      name: "Search audit events",
    });
    await userEvent.type(search, "CAMPAIGN-B");
    const table = screen.getByRole("region", {
      name: "Local draft audit events",
    });
    expect(within(table).getAllByRole("row")).toHaveLength(2);
    expect(within(table).getByText("campaign.created")).toBeVisible();
    expect(screen.getByText("1 / 2")).toBeVisible();
    await userEvent.clear(search);
    await userEvent.type(search, "not-present");
    expect(
      screen.getByRole("heading", { name: "No matching events" }),
    ).toBeVisible();
    expect(
      screen.queryByRole("heading", { name: "No draft activity recorded" }),
    ).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Clear search" }));
    expect(search).toHaveValue("");
    expect(
      within(
        screen.getByRole("region", { name: "Local draft audit events" }),
      ).getAllByRole("row"),
    ).toHaveLength(3);
  });
});

describe("workspace refresh states", () => {
  it.each([
    "CampaignsPage",
    "FindingsPage",
    "EvidencePage",
    "ApprovalsPage",
    "AuditPage",
  ])(
    "%s announces pending/error/retry without inventing new data",
    async (name) => {
      const input = props();
      let reject!: (reason: Error) => void;
      vi.mocked(input.refresh)
        .mockImplementationOnce(
          () =>
            new Promise((_resolve, fail) => {
              reject = fail;
            }),
        )
        .mockResolvedValue(undefined);
      const Page = page(name);
      render(<Page {...input} />);
      await userEvent.click(
        screen.getByRole("button", { name: "Refresh workspace" }),
      );
      expect(
        screen.getByRole("button", { name: "Refreshing…" }),
      ).toBeDisabled();
      expect(screen.getByRole("status")).toHaveTextContent(
        "Loading the latest workspace snapshot…",
      );
      await act(async () => reject(new Error("offline")));
      expect(screen.getByRole("alert")).toHaveTextContent(
        "Could not refresh. Displayed data may be stale. Retry when the local API is available.",
      );
      await userEvent.click(
        screen.getByRole("button", { name: "Retry refresh" }),
      );
      await waitFor(() =>
        expect(screen.queryByRole("alert")).not.toBeInTheDocument(),
      );
      expect(screen.getByRole("status")).toHaveTextContent(
        "Workspace refreshed.",
      );
      expect(input.refresh).toHaveBeenCalledTimes(2);
    },
  );
});

describe("operations entry point", () => {
  it("exports all six production pages through the agreed barrel", () => {
    const entries = import.meta.glob<Record<string, ComponentType<PageProps>>>(
      "./index.ts",
      { eager: true },
    );
    expect(Object.keys(entries["./index.ts"] ?? {}).sort()).toEqual([
      "ApprovalsPage",
      "AuditPage",
      "CampaignsPage",
      "EvidencePage",
      "FindingsPage",
      "RunsPage",
    ]);
  });
});

describe("campaign dialog lifecycle", () => {
  it("allows dismissal during saving while preserving a visible in-flight operation and blocking duplicates", async () => {
    const input = props(readyWorkspace());
    let finish!: (value: Response) => void;
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    const CampaignsPage = page("CampaignsPage");
    render(<CampaignsPage {...input} />);
    const dialog = await fillCampaign();
    await userEvent.click(
      within(dialog).getByRole("button", { name: "Save draft" }),
    );
    fireEvent(dialog, new Event("cancel", { bubbles: true, cancelable: true }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(
      "Saving the draft. Closing the dialog does not cancel the request.",
    );
    expect(screen.getByRole("button", { name: "New campaign" })).toBeDisabled();
    await act(async () =>
      finish(
        new Response(
          JSON.stringify({
            id: "created",
            name: "Review policy",
            objective: "A bounded lab review",
            target_id: "target-1",
            profile_id: "profile-1",
            status: "draft",
            created_at: "",
          }),
          { status: 201 },
        ),
      ),
    );
    expect(input.refresh).toHaveBeenCalledOnce();
    expect(fetchMock).toHaveBeenCalledOnce();
    expect(screen.getByRole("status")).toHaveTextContent(
      "Campaign draft saved. No execution was started.",
    );
  });

  it("reports a failed request after dismissal and lets the operator resume preserved input", async () => {
    const input = props(readyWorkspace());
    let reject!: (reason: Error) => void;
    vi.spyOn(globalThis, "fetch").mockImplementation(
      () =>
        new Promise((_resolve, fail) => {
          reject = fail;
        }),
    );
    const CampaignsPage = page("CampaignsPage");
    render(<CampaignsPage {...input} />);
    const dialog = await fillCampaign();
    await userEvent.click(
      within(dialog).getByRole("button", { name: "Save draft" }),
    );
    fireEvent(dialog, new Event("cancel", { bubbles: true, cancelable: true }));
    await act(async () => reject(new Error("offline")));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(
      "The draft could not be saved. Your input is preserved; check the workspace and try again.",
    );
    await userEvent.click(screen.getByRole("button", { name: "Resume draft" }));
    expect(
      within(screen.getByRole("dialog")).getByLabelText("Campaign name"),
    ).toHaveValue("Review policy");
  });

  it("shows a limit explanation inside an already open form if the snapshot reaches its cap", async () => {
    const input = props(readyWorkspace());
    const create = vi.spyOn(api, "createCampaign");
    const CampaignsPage = page("CampaignsPage");
    const view = render(<CampaignsPage {...input} />);
    const dialog = await fillCampaign();
    const data = readyWorkspace();
    data.campaigns = Array.from({ length: 100 }, (_, index) => ({
      id: `c-${index}`,
      name: `Draft ${index}`,
      objective: "Test objective",
      target_id: "target-1",
      profile_id: "profile-1",
      status: "draft" as const,
      created_at: "",
    }));
    view.rerender(<CampaignsPage {...input} data={data} />);
    expect(
      within(dialog).getByRole("button", { name: "Save draft" }),
    ).toBeDisabled();
    expect(
      within(dialog).getByText(
        "The local limit of 100 campaign drafts has been reached. Additional drafts cannot be saved.",
      ),
    ).toBeVisible();
    fireEvent.submit(dialog.querySelector("form")!);
    expect(create).not.toHaveBeenCalled();
  });
});

describe("campaign input boundaries", () => {
  it.each([
    ["blank name", "   ", "Review policy"],
    ["blank objective", "Policy review", "   "],
    ["long name", "x".repeat(121), "Review policy"],
    ["long objective", "Policy review", "x".repeat(2001)],
  ])("rejects %s before sending a request", async (_case, name, objective) => {
    const input = props(readyWorkspace());
    const create = vi
      .spyOn(api, "createCampaign")
      .mockResolvedValue({
        id: "unexpected",
        name,
        objective,
        target_id: "target-1",
        profile_id: "profile-1",
        status: "draft",
        created_at: "",
      });
    const CampaignsPage = page("CampaignsPage");
    render(<CampaignsPage {...input} />);
    await userEvent.click(screen.getByRole("button", { name: "New campaign" }));
    const dialog = screen.getByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("Campaign name"), {
      target: { value: name },
    });
    fireEvent.change(within(dialog).getByLabelText("Objective"), {
      target: { value: objective },
    });
    await userEvent.selectOptions(
      within(dialog).getByLabelText("Target"),
      "target-1",
    );
    await userEvent.selectOptions(
      within(dialog).getByLabelText("Profile template"),
      "profile-1",
    );
    fireEvent.submit(dialog.querySelector("form")!);
    expect(create).not.toHaveBeenCalled();
    expect(within(dialog).getByRole("alert")).toHaveTextContent(
      "Enter a name of 1–120 characters and an objective of 1–2,000 characters.",
    );
  });

  it("rechecks target and profile membership against refreshed props before saving", async () => {
    const input = props(readyWorkspace());
    const create = vi
      .spyOn(api, "createCampaign")
      .mockResolvedValue({
        id: "unexpected",
        name: "Review",
        objective: "Review policy",
        target_id: "target-1",
        profile_id: "profile-1",
        status: "draft",
        created_at: "",
      });
    const CampaignsPage = page("CampaignsPage");
    const view = render(<CampaignsPage {...input} />);
    await userEvent.click(screen.getByRole("button", { name: "New campaign" }));
    const dialog = screen.getByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("Campaign name"), {
      target: { value: "Review" },
    });
    fireEvent.change(within(dialog).getByLabelText("Objective"), {
      target: { value: "Review policy" },
    });
    await userEvent.selectOptions(
      within(dialog).getByLabelText("Target"),
      "target-1",
    );
    await userEvent.selectOptions(
      within(dialog).getByLabelText("Profile template"),
      "profile-1",
    );
    view.rerender(<CampaignsPage {...input} data={workspaceFixture()} />);
    fireEvent.submit(dialog.querySelector("form")!);
    expect(create).not.toHaveBeenCalled();
    expect(within(dialog).getByRole("alert")).toHaveTextContent(
      "Select a target and a profile that exist in the current workspace.",
    );
  });
});
