import type { ComponentType } from "react";
import { useCallback, useEffect, useRef, useState } from "react";
import type { Locale, PageProps, WorkspaceSnapshot } from "./lib/contracts";
import type { RouteId } from "./lib/navigation";
import { navigation, routeFromPath } from "./lib/navigation";
import { api } from "./lib/api";
import { choose, text } from "./lib/i18n";
import { WorkspaceShell } from "./components/WorkspaceShell";
import { Button, Notice, PageHeader, Panel } from "./components/ui";
export type ApplicationProps = {
  pages: Record<RouteId, ComponentType<PageProps>>;
};
export function Application({ pages }: ApplicationProps) {
  const [route, setRoute] = useState(() =>
    routeFromPath(window.location.pathname),
  );
  const [locale, setLocale] = useState<Locale>(() => {
    try {
      const saved = localStorage.getItem("aegis.locale");
      if (saved === "en" || saved === "ko") return saved;
    } catch {
      /* Storage may be blocked; language still works for this tab. */
    }
    return navigator.language.startsWith("ko") ? "ko" : "en";
  });
  const [data, setData] = useState<WorkspaceSnapshot | null>(null);
  const [connection, setConnection] = useState<"loading" | "ready" | "error">(
    "loading",
  );
  const activeRequest = useRef<AbortController | null>(null);
  const generation = useRef(0);
  const refresh = useCallback(async () => {
    activeRequest.current?.abort();
    const controller = new AbortController();
    activeRequest.current = controller;
    const current = ++generation.current;
    setConnection("loading");
    try {
      const next = await api.getWorkspace(controller.signal);
      if (current === generation.current && !controller.signal.aborted) {
        setData(next);
        setConnection("ready");
      }
    } catch {
      if (current === generation.current && !controller.signal.aborted)
        setConnection("error");
      throw new Error("Workspace refresh failed.");
    }
  }, []);
  useEffect(() => {
    void refresh().catch(() => undefined);
    return () => activeRequest.current?.abort();
  }, [refresh]);
  useEffect(() => {
    const back = () => setRoute(routeFromPath(window.location.pathname));
    window.addEventListener("popstate", back);
    return () => window.removeEventListener("popstate", back);
  }, []);
  useEffect(() => {
    document.documentElement.lang = locale;
    const item = navigation.find((item) => item.id === route);
    document.title =
      (item ? text(item.label, locale) : "Aegis Lab") + " · Aegis Lab";
  }, [locale, route]);
  useEffect(() => {
    try {
      localStorage.setItem("aegis.locale", locale);
    } catch {
      /* Preferences are not a prerequisite for using the workspace. */
    }
  }, [locale]);
  const navigate = (next: RouteId) => {
    window.history.pushState(null, "", "/" + next);
    setRoute(next);
    document.getElementById("main-content")?.focus({ preventScroll: true });
  };
  const Page = route ? pages[route] : null;
  return (
    <WorkspaceShell
      route={route}
      locale={locale}
      setLocale={setLocale}
      navigate={navigate}
      connection={connection}
    >
      {connection === "error" && (
        <section className="connection-error-panel" role="alert">
          <h2>
            {choose(
              locale,
              "Local API is unavailable",
              "로컬 API에 연결할 수 없습니다",
            )}
          </h2>
          <p>
            {choose(
              locale,
              "Check that the development API is running, then retry. No sample data is substituted.",
              "개발 API가 실행 중인지 확인한 뒤 재시도하세요. 임의의 예시 데이터로 대체하지 않습니다.",
            )}
          </p>
          <code>make api</code>
          <div>
            <Button
              variant="primary"
              onClick={() => void refresh().catch(() => undefined)}
            >
              {choose(locale, "Retry connection", "연결 재시도")}
            </Button>
          </div>
        </section>
      )}
      {!Page ? (
        <div className="page-stack">
          <PageHeader
            title={choose(
              locale,
              "Page not found",
              "페이지를 찾을 수 없습니다",
            )}
            description={choose(
              locale,
              "This address does not match a workspace page.",
              "워크스페이스에 없는 주소입니다.",
            )}
          />
          <Panel>
            <Button onClick={() => navigate("overview")}>
              {choose(locale, "Back to overview", "개요로 돌아가기")}
            </Button>
          </Panel>
        </div>
      ) : data ? (
        <>
          {connection === "error" && (
            <div className="stale-notice">
              <Notice tone="warning">
                {choose(
                  locale,
                  "Showing the last loaded snapshot. Editing is disabled until the API reconnects.",
                  "마지막으로 불러온 상태를 표시하고 있습니다. API에 다시 연결될 때까지 편집할 수 없습니다.",
                )}
              </Notice>
            </div>
          )}
          <fieldset className="page-fieldset" disabled={connection !== "ready"}>
            <Page
              data={data}
              locale={locale}
              navigate={navigate}
              refresh={refresh}
            />
          </fieldset>
        </>
      ) : (
        connection !== "error" && (
          <div className="loading-workspace" role="status">
            <span className="loading-spinner" aria-hidden="true" />
            {choose(
              locale,
              "Loading local workspace…",
              "로컬 워크스페이스 불러오는 중…",
            )}
          </div>
        )
      )}
    </WorkspaceShell>
  );
}
