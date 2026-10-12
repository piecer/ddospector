import type { ComponentType } from "react";
import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Application } from "./App";
import { api } from "./lib/api";
import { navigation } from "./lib/navigation";
import type { RouteId } from "./lib/navigation";
import type { PageProps } from "./lib/contracts";
import { workspaceFixture } from "./test/fixtures";
import html from "../index.html?raw";
import packageMetadata from "../package.json";
import packageLock from "../package-lock.json";

const pages = Object.fromEntries(
  navigation.map((item) => [
    item.id,
    ({ locale }: PageProps) => <h1 lang={locale}>{item.id}</h1>,
  ]),
) as Record<RouteId, ComponentType<PageProps>>;
const description =
  "AI-powered open-source framework for automated DDoS defense testing, mitigation gap discovery, and security validation.";

beforeEach(() => {
  localStorage.clear();
  window.history.replaceState(null, "", "/overview");
  vi.spyOn(api, "getWorkspace").mockResolvedValue(workspaceFixture());
});
afterEach(() => vi.restoreAllMocks());

describe("DDoSpector branding", () => {
  it("uses the exact visible and accessible brand without changing offline limits", async () => {
    const { container } = render(<Application pages={pages} />);
    await screen.findByRole("heading", { name: "overview" });
    expect(container.querySelector(".brand strong")).toHaveTextContent(
      /^DDoSpector$/,
    );
    expect(
      screen.getByRole("button", { name: /^DDoSpector$/ }),
    ).toBeInTheDocument();
    expect(container.querySelector(".content-footer")).toHaveTextContent(
      "DDoSpector",
    );
    expect(screen.getByText("LIVE execution locked")).toBeInTheDocument();
    expect(screen.getByText("Drafts only · No test traffic")).toBeInTheDocument();
    expect(screen.getByText("OFFLINE", { exact: true })).toBeInTheDocument();
  });

  it("brands the route title and keeps brand navigation working", async () => {
    window.history.replaceState(null, "", "/targets");
    render(<Application pages={pages} />);
    await screen.findByRole("heading", { name: "targets" });
    expect(document.title).toBe("Targets · DDoSpector");
    await userEvent.click(
      screen.getByRole("button", { name: /^DDoSpector$/ }),
    );
    expect(window.location.pathname).toBe("/overview");
    expect(document.title).toBe("Overview · DDoSpector");
  });

  it("brands the unknown-route title", async () => {
    window.history.replaceState(null, "", "/unknown-page");
    render(<Application pages={pages} />);
    await screen.findByRole("heading", { name: "Page not found" });
    expect(document.title).toBe("DDoSpector · DDoSpector");
  });

  it("restores an existing legacy language preference across the rename", async () => {
    localStorage.setItem("aegis.locale", "ko");
    const first = render(<Application pages={pages} />);
    await screen.findByRole("heading", { name: "overview" });
    expect(screen.getByRole("combobox", { name: "화면 언어" })).toHaveValue("ko");
    expect(document.documentElement.lang).toBe("ko");
    expect(document.title).toBe("워크스페이스 · DDoSpector");
    await userEvent.click(
      within(screen.getByRole("navigation")).getByRole("link", {
        name: "시험 대상",
      }),
    );
    expect(document.title).toBe("시험 대상 · DDoSpector");
    await userEvent.selectOptions(
      screen.getByRole("combobox", { name: "화면 언어" }),
      "en",
    );
    expect(localStorage.getItem("aegis.locale")).toBe("en");
    first.unmount();
    render(<Application pages={pages} />);
    await screen.findByRole("heading", { name: "targets" });
    expect(
      screen.getByRole("combobox", { name: "Interface language" }),
    ).toHaveValue("en");
    expect(document.title).toBe("Targets · DDoSpector");
  });

  it("ships the exact HTML brand and NAME description", () => {
    const entry = new DOMParser().parseFromString(html, "text/html");
    expect.soft(entry.title).toBe("DDoSpector");
    expect(
      entry.querySelector('meta[name="description"]')?.getAttribute("content"),
    ).toBe(description);
  });

  it("keeps npm and lockfile root names aligned", () => {
    expect.soft(packageMetadata.name).toBe("ddospector-ui");
    expect.soft(packageLock.name).toBe("ddospector-ui");
    expect(packageLock.packages[""].name).toBe("ddospector-ui");
  });
});
