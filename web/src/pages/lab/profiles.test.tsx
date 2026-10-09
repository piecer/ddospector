import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import type { PageProps, TrafficProfile } from "../../lib/contracts";
import { workspaceFixture } from "../../test/fixtures";
import { ProfilesPage } from "./index";

afterEach(() => vi.unstubAllGlobals());
function props(overrides: Partial<PageProps> = {}): PageProps {
  return {
    data: workspaceFixture(),
    locale: "en",
    navigate: vi.fn(),
    refresh: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  };
}
// Synthetic catalog projections, only in tests. Production renders data.profiles.
const templates: TrafficProfile[] = [
  {
    id: "tcpreplay-policy",
    name: { en: "Synthetic replay template", ko: "테스트 재생 템플릿" },
    description: {
      en: "Synthetic replay description.",
      ko: "테스트 재생 설명입니다.",
    },
    engine: "tcpreplay",
    layer: "L2–L4",
    status: "template",
  },
  {
    id: "tcpdump-observer",
    name: { en: "Synthetic observation template", ko: "테스트 관측 템플릿" },
    description: {
      en: "Synthetic observation description.",
      ko: "테스트 관측 설명입니다.",
    },
    engine: "tcpdump",
    layer: "L2–L4",
    status: "template",
  },
  {
    id: "k6-http",
    name: { en: "Synthetic HTTP template", ko: "테스트 HTTP 템플릿" },
    description: {
      en: "Synthetic HTTP description.",
      ko: "테스트 HTTP 설명입니다.",
    },
    engine: "k6",
    layer: "L7",
    status: "template",
  },
];

describe("ProfilesPage", () => {
  it.each([
    ["en", "No profile templates available"],
    ["ko", "사용 가능한 프로파일 템플릿이 없습니다"],
  ] as const)(
    "does not fabricate a missing catalog in %s",
    (locale, heading) => {
      render(<ProfilesPage {...props({ locale })} />);
      expect(
        screen.getByRole("heading", { name: heading }),
      ).toBeInTheDocument();
      expect(
        screen.queryByRole("button", { name: /View details|상세 보기/ }),
      ).not.toBeInTheDocument();
    },
  );

  it.each(["en", "ko"] as const)(
    "renders exactly the supplied templates and a useful detail view in %s",
    (locale) => {
      const fetch = vi.fn();
      vi.stubGlobal("fetch", fetch);
      const data = workspaceFixture();
      data.profiles = templates;
      const page = props({ data, locale });
      render(<ProfilesPage {...page} />);
      for (const template of templates)
        expect(
          screen.getByRole("heading", { name: template.name[locale] }),
        ).toBeInTheDocument();
      const view = locale === "en" ? "View details: " : "상세 보기: ";
      expect(
        screen.getAllByRole("button", { name: new RegExp(view) }),
      ).toHaveLength(3);
      fireEvent.click(
        screen.getByRole("button", { name: view + templates[2].name[locale] }),
      );
      const dialog = screen.getByRole("dialog");
      expect(within(dialog).getByText("k6-http")).toBeInTheDocument();
      expect(
        within(dialog).getByText(templates[2].description[locale]),
      ).toBeInTheDocument();
      expect(
        within(dialog).getByRole("button", {
          name: locale === "en" ? "Execute profile" : "프로파일 실행",
        }),
      ).toBeDisabled();
      expect(
        within(dialog).getByText(
          locale === "en"
            ? "Templates do not authorize execution. Live execution is unavailable."
            : "템플릿은 실행 권한을 부여하지 않습니다. 실제 실행은 사용할 수 없습니다.",
        ),
      ).toBeInTheDocument();
      fireEvent.click(
        within(dialog).getByRole("button", {
          name: locale === "en" ? "Open campaign drafts" : "캠페인 초안 열기",
        }),
      );
      expect(page.navigate).toHaveBeenCalledWith("campaigns");
      expect(fetch).not.toHaveBeenCalled();
    },
  );
});
