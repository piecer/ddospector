import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { WorkspaceShell } from "./WorkspaceShell";
function mount(locale: "en" | "ko" = "en") {
  const navigate = vi.fn();
  const setLocale = vi.fn();
  render(
    <WorkspaceShell
      route="overview"
      locale={locale}
      setLocale={setLocale}
      navigate={navigate}
      connection="ready"
    >
      <div>Page body</div>
    </WorkspaceShell>,
  );
  return { navigate, setLocale };
}
describe("workspace shell", () => {
  it("exposes all menu routes and a truthful OFFLINE state", () => {
    mount();
    expect(screen.getByRole("navigation")).toBeInTheDocument();
    expect(
      screen
        .getAllByRole("link")
        .filter((link) => link.getAttribute("href")?.startsWith("/")),
    ).toHaveLength(14);
    expect(screen.getByRole("link", { name: "Overview" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.getAllByText("OFFLINE").length).toBeGreaterThan(0);
    expect(screen.getByText("Page body")).toBeInTheDocument();
  });
  it("changes language explicitly", async () => {
    const { setLocale } = mount();
    await userEvent.selectOptions(
      screen.getByRole("combobox", { name: "Interface language" }),
      "ko",
    );
    expect(setLocale).toHaveBeenCalledWith("ko");
  });
  it("opens keyboard navigation search and routes to Skills", async () => {
    const { navigate } = mount();
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    const field = screen.getByRole("textbox", { name: "Find a page" });
    await userEvent.type(field, "Skill");
    await userEvent.click(
      screen.getByRole("button", { name: /Skill library/ }),
    );
    expect(navigate).toHaveBeenCalledWith("skills");
  });
  it("labels the shell in Korean", () => {
    mount("ko");
    expect(
      screen.getByRole("link", { name: "Skill 라이브러리" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("combobox", { name: "화면 언어" }),
    ).toBeInTheDocument();
  });
});
