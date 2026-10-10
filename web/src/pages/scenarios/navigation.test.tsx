import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { CampaignsPage } from "../operations/CampaignsPage";
import { workspaceFixture } from "../../test/fixtures";
it.each(["en", "ko"] as const)(
  "offers a planning-only scenario library link in %s",
  (locale) => {
    const navigate = vi.fn();
    render(
      <CampaignsPage
        locale={locale}
        data={workspaceFixture()}
        navigate={navigate}
        refresh={vi.fn()}
      />,
    );
    fireEvent.click(
      screen.getByRole("button", {
        name:
          locale === "en"
            ? "Open scenario library"
            : "시나리오 라이브러리 열기",
      }),
    );
    expect(navigate).toHaveBeenCalledWith("profiles");
    expect(
      screen.getByRole("button", {
        name: locale === "en" ? "New campaign" : "새 캠페인",
      }),
    ).toBeDisabled();
  },
);
