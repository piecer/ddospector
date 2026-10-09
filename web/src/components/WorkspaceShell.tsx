import type { ReactNode } from "react";
import { useEffect, useRef, useState } from "react";
import {
  Activity,
  ArrowRight,
  BookOpen,
  Bot,
  ChevronRight,
  Circle,
  Crosshair,
  FolderArchive,
  History,
  Languages,
  Layers3,
  LayoutDashboard,
  LockKeyhole,
  Menu,
  Network,
  RadioTower,
  ScanSearch,
  Search,
  Settings2,
  ShieldCheck,
  SlidersHorizontal,
  X,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type { Locale } from "../lib/contracts";
import type { RouteId } from "../lib/navigation";
import { navigation } from "../lib/navigation";
import { choose, text } from "../lib/i18n";
import { Badge, Button, Dialog } from "./ui";
export type ShellProps = {
  locale: Locale;
  setLocale: (locale: Locale) => void;
  route: RouteId | null;
  navigate: (route: RouteId) => void;
  connection: "loading" | "ready" | "error";
  children: ReactNode;
};
const icons: Record<string, LucideIcon> = {
  Activity,
  BookOpen,
  Bot,
  Crosshair,
  FolderArchive,
  History,
  Layers3,
  LayoutDashboard,
  Network,
  RadioTower,
  ScanSearch,
  Settings2,
  ShieldCheck,
  SlidersHorizontal,
};
const groupLabels = {
  workspace: { en: "Workspace", ko: "워크스페이스" },
  lab: { en: "Lab configuration", ko: "실험 환경" },
  ai: { en: "AI & governance", ko: "AI · 거버넌스" },
  system: { en: "System", ko: "시스템" },
};

export function WorkspaceShell({
  locale,
  setLocale,
  route,
  navigate,
  connection,
  children,
}: ShellProps) {
  const [searchOpen, setSearchOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [mobileOpen, setMobileOpen] = useState(false);
  const menuButton = useRef<HTMLButtonElement>(null);
  const current = navigation.find((item) => item.id === route);
  const c = (en: string, ko: string) => choose(locale, en, ko);
  const openSearch = () => {
    setQuery("");
    setSearchOpen(true);
  };
  useEffect(() => {
    if (searchOpen)
      document
        .querySelector<HTMLInputElement>(".command-search input")
        ?.focus();
  }, [searchOpen]);
  useEffect(() => {
    const handle = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setQuery("");
        setSearchOpen(true);
      }
      if (event.key === "Escape" && !document.querySelector("dialog[open]")) {
        setMobileOpen(false);
        menuButton.current?.focus();
      }
    };
    window.addEventListener("keydown", handle);
    return () => window.removeEventListener("keydown", handle);
  }, []);
  const go = (id: RouteId) => {
    navigate(id);
    setSearchOpen(false);
    setMobileOpen(false);
  };
  const matches = navigation.filter((item) =>
    (item.id + " " + item.label.en + " " + item.label.ko)
      .toLowerCase()
      .includes(query.trim().toLowerCase()),
  );

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">
        {c("Skip to content", "본문으로 건너뛰기")}
      </a>
      {mobileOpen && (
        <button
          className="nav-backdrop"
          aria-label={c("Close navigation", "메뉴 닫기")}
          onClick={() => setMobileOpen(false)}
        />
      )}
      <aside
        id="workspace-navigation"
        className={"sidebar " + (mobileOpen ? "sidebar-open" : "")}
      >
        <div className="brand-row">
          <button
            className="brand"
            onClick={() => go("overview")}
            aria-label="Aegis Lab"
          >
            <span className="brand-mark">
              <ShieldCheck size={23} strokeWidth={1.65} aria-hidden="true" />
            </span>
            <span>
              <strong>
                AEGIS<span className="brand-light"> LAB</span>
              </strong>
              <small>DEFENSE VALIDATION</small>
            </span>
          </button>
          <Button
            className="mobile-close"
            variant="ghost"
            onClick={() => setMobileOpen(false)}
            aria-label={c("Close menu", "메뉴 닫기")}
          >
            <X size={18} />
          </Button>
        </div>
        <div className="workspace-switch">
          <span className="workspace-avatar">L</span>
          <div>
            <strong>{c("Local workspace", "로컬 워크스페이스")}</strong>
            <small>{c("Draft configuration", "초안 구성")}</small>
          </div>
          <Badge>01</Badge>
        </div>
        <nav
          aria-label={c("Main navigation", "주 메뉴")}
          className="navigation"
        >
          {(Object.keys(groupLabels) as Array<keyof typeof groupLabels>).map(
            (group) => (
              <div className="nav-group" key={group}>
                <div className="nav-group-label">
                  {text(groupLabels[group], locale)}
                </div>
                {navigation
                  .filter((item) => item.group === group)
                  .map((item) => {
                    const Icon = icons[item.icon] ?? Circle;
                    return (
                      <a
                        key={item.id}
                        href={"/" + item.id}
                        className={
                          "nav-item " +
                          (item.id === route ? "nav-item-active" : "")
                        }
                        aria-current={item.id === route ? "page" : undefined}
                        onClick={(event) => {
                          if (
                            !event.metaKey &&
                            !event.ctrlKey &&
                            !event.shiftKey &&
                            !event.altKey &&
                            event.button === 0
                          ) {
                            event.preventDefault();
                            go(item.id);
                          }
                        }}
                      >
                        <Icon size={17} strokeWidth={1.65} aria-hidden="true" />
                        <span>{text(item.label, locale)}</span>
                        {item.id === "agent" && (
                          <span className="nav-ai-tag">AI</span>
                        )}
                      </a>
                    );
                  })}
              </div>
            ),
          )}
        </nav>
        <div className="sidebar-footer">
          <div className="local-indicator">
            <span className="status-dot" />
            {c("Local development", "로컬 개발 환경")}
          </div>
          <div className="sidebar-safety">
            <LockKeyhole size={13} aria-hidden="true" />
            {c("LIVE execution locked", "LIVE 실행 잠김")}
            <span className="mono">v0.1</span>
          </div>
        </div>
      </aside>
      <div className="workspace-main">
        <header className="topbar">
          <div className="topbar-start">
            <button
              ref={menuButton}
              className="icon-button mobile-menu"
              aria-label={c("Open navigation", "메뉴 열기")}
              aria-controls="workspace-navigation"
              aria-expanded={mobileOpen}
              onClick={() => setMobileOpen((value) => !value)}
            >
              <Menu size={21} />
            </button>
            <span className="breadcrumb-root">
              {c("Workspace", "워크스페이스")}
            </span>
            <ChevronRight
              size={13}
              className="breadcrumb-chevron"
              aria-hidden="true"
            />
            <span className="breadcrumb-current">
              {current
                ? text(current.label, locale)
                : c("Not found", "페이지 없음")}
            </span>
          </div>
          <div className="topbar-end">
            <button
              className="workspace-search"
              onClick={openSearch}
              aria-label={c("Search workspace", "워크스페이스 검색")}
            >
              <Search size={15} />
              <span>{c("Search pages", "메뉴 검색")}</span>
              <kbd>Ctrl K</kbd>
            </button>
            <span
              className={"connection-indicator connection-" + connection}
              title={c(
                "Local API connectivity only; not instrument readiness",
                "로컬 API 연결 상태이며 계측기 준비 상태가 아닙니다",
              )}
            >
              <span className="status-dot" />
              <span>
                {connection === "ready"
                  ? c("Local API", "로컬 API")
                  : connection === "loading"
                    ? c("Connecting", "연결 중")
                    : c("API offline", "API 미연결")}
              </span>
            </span>
            <div className="language-control">
              <Languages size={15} aria-hidden="true" />
              <select
                aria-label={c("Interface language", "화면 언어")}
                value={locale}
                onChange={(event) => setLocale(event.target.value as Locale)}
              >
                <option value="en">EN</option>
                <option value="ko">한국어</option>
              </select>
            </div>
            <Badge tone="warning">OFFLINE</Badge>
          </div>
        </header>
        <main id="main-content" className="main-content" tabIndex={-1}>
          {children}
          <footer className="content-footer">
            <span>
              AEGIS LAB <span aria-hidden="true">/</span>{" "}
              {c("Evidence before conclusions.", "결론보다 먼저, 증거.")}
            </span>
            <span>
              {c(
                "Drafts only · No test traffic",
                "초안 전용 · 시험 트래픽 없음",
              )}
            </span>
          </footer>
        </main>
      </div>
      <Dialog
        open={searchOpen}
        title={c("Go to a page", "메뉴로 이동")}
        onClose={() => setSearchOpen(false)}
      >
        <div className="command-search">
          <Search size={18} aria-hidden="true" />
          <input
            aria-label={c("Find a page", "메뉴 찾기")}
            placeholder={c("Search pages…", "메뉴 검색…")}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => {
              if (
                event.key === "Enter" &&
                !event.nativeEvent.isComposing &&
                matches[0]
              ) {
                event.preventDefault();
                go(matches[0].id);
              }
            }}
          />
        </div>
        <div className="command-results">
          {matches.map((item) => {
            const Icon = icons[item.icon] ?? Circle;
            return (
              <button key={item.id} onClick={() => go(item.id)}>
                <Icon size={17} aria-hidden="true" />
                <span>
                  {text(item.label, locale)}
                  <small>{text(groupLabels[item.group], locale)}</small>
                </span>
                <ArrowRight size={15} aria-hidden="true" />
              </button>
            );
          })}
          {matches.length === 0 && (
            <p className="muted">
              {c("No matching pages.", "일치하는 메뉴가 없습니다.")}
            </p>
          )}
        </div>
      </Dialog>
    </div>
  );
}
