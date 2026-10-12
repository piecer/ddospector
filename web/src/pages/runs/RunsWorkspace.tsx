import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { Activity, ShieldCheck, RefreshCw } from "lucide-react";
import {
  Badge,
  Button,
  DataTable,
  EmptyState,
  Field,
  Notice,
  PageHeader,
  Panel,
} from "../../components/ui";
import type { PageProps } from "../../lib/contracts";
import { choose } from "../../lib/i18n";
import { LockedAction, RefreshWorkspace } from "../operations/common";
import { scenarioAPI } from "../scenarios/client";
import { ScenarioDetails } from "../scenarios/ScenarioDetails";
import type { ScenarioPage, ScenarioHistory } from "../scenarios/types";
import { canonical } from "../scenarios/json";
import { runsController } from "./controller";
import { runAPI } from "./transport";
import { RunError } from "./errors";
import { errorText, term } from "./labels";
import { bindList } from "./checkpoint";
import type { RunPage, Summary } from "./types";
import { RunDetails } from "./RunDetails";
import "./runs.css";
import "../scenarios/scenarios.css";
type ReadState = "loading" | "ready" | "error";
export function RunsWorkspace({ locale, navigate, refresh }: PageProps) {
  const t = (en: string, ko: string) => choose(locale, en, ko),
    c = runsController();
  useSyncExternalStore(c.subscribe, c.getSnapshot);
  const [list, setList] = useState<RunPage | null>(null),
    [listState, setListState] = useState<ReadState>("loading"),
    [listError, setListError] = useState<string | null>(null);
  const [pageRequest, setPageRequest] = useState<{
    after: number;
    through?: number;
    reload: number;
  }>({ after: 0, reload: 0 });
  const [sources, setSources] = useState<ScenarioPage | null>(null),
    [sourceState, setSourceState] = useState<ReadState>("loading"),
    [sourceOffset, setSourceOffset] = useState(0),
    [sourceReload, setSourceReload] = useState(0);
  const [scenarioId, setScenarioId] = useState(""),
    [history, setHistory] = useState<ScenarioHistory | null>(null),
    [historyState, setHistoryState] = useState<ReadState>("ready"),
    [version, setVersion] = useState(1);
  const [directId, setDirectId] = useState(""),
    [directInvalid, setDirectInvalid] = useState(false);
  const invoker = useRef<HTMLElement | null>(null);
  useEffect(() => {
    void c.start();
    return () => c.leave();
  }, [c]);
  useEffect(() => {
    const abort = new AbortController();
    void runAPI
      .list(pageRequest.after, 20, pageRequest.through, abort.signal)
      .then(
        (value) => {
          if (abort.signal.aborted) return;
          try {
            const view = c.view,
              row = value.items.find((x) => x.id === view?.id);
            if (row && view?.detail) bindList(row, view.detail.run);
            if (row && view?.summary) bindList(row, view.summary);
            setList(value);
            setListState("ready");
            setListError(null);
          } catch {
            setListState("error");
            setListError("RUN_CLIENT_INVALID");
          }
        },
        (e) => {
          if (!abort.signal.aborted) {
            setListState("error");
            setListError(e instanceof RunError ? e.code : "RUN_CLIENT_INVALID");
          }
        },
      );
    return () => abort.abort();
  }, [pageRequest, c]);
  useEffect(() => {
    const abort = new AbortController();
    void scenarioAPI.read(sourceOffset, 20, abort.signal).then(
      (value) => {
        if (!abort.signal.aborted) {
          setSources(value);
          setSourceState("ready");
        }
      },
      () => {
        if (!abort.signal.aborted) setSourceState("error");
      },
    );
    return () => abort.abort();
  }, [sourceOffset, sourceReload]);
  useEffect(() => {
    if (!scenarioId) return;
    const abort = new AbortController();
    void scenarioAPI.history(scenarioId, abort.signal).then(
      (value) => {
        if (abort.signal.aborted) return;
        const listed = sources?.items.find((x) => x.id === scenarioId);
        if (
          listed &&
          !value.versions.some((x) => canonical(x) === canonical(listed))
        ) {
          setHistoryState("error");
          return;
        }
        setHistory(value);
        setVersion(value.versions.at(-1)!.version);
        setHistoryState("ready");
      },
      () => {
        if (!abort.signal.aborted) setHistoryState("error");
      },
    );
    return () => abort.abort();
  }, [scenarioId, sources]);
  const selected =
    history?.scenario_id === scenarioId && historyState === "ready"
      ? history.versions.find((x) => x.version === version)
      : undefined;
  const canStart =
    !!selected &&
    sourceState === "ready" &&
    listState === "ready" &&
    c.store.canSubmit &&
    !c.busy;
  function show(id: string, summary: Summary | null = null) {
    try {
      const v = c.select(id, summary);
      setDirectInvalid(false);
      if (!v.detail) void c.read();
    } catch {
      setDirectInvalid(true);
    }
  }
  function refreshRuns() {
    setListState("loading");
    setPageRequest({ after: 0, reload: pageRequest.reload + 1 });
  }
  const pending = c.store.receipt;
  return (
    <div className="page-stack operations-page runs-page">
      <PageHeader
        eyebrow={t(
          "Workspace / OFFLINE preparation",
          "워크스페이스 / OFFLINE 준비",
        )}
        title={t("Runs", "실행")}
        description={t(
          "Compile captured scenario declarations. Review durable progress without contacting equipment.",
          "캡처한 시나리오 선언을 정리합니다. 장비에 접속하지 않고 영속 진행 상태를 확인합니다.",
        )}
        actions={
          <LockedAction
            label={t("Start run", "실행 시작")}
            reason={t(
              "Live execution is disabled on the server. Campaign drafts do not start runs.",
              "서버에서 라이브 실행이 비활성화되어 있습니다. 캠페인 초안은 실행되지 않습니다.",
            )}
          />
        }
      />
      <RefreshWorkspace locale={locale} refresh={refresh} />
      <Notice>
        <ShieldCheck size={16} aria-hidden="true" />{" "}
        {t(
          "OFFLINE only: no traffic, device contact, DNS, model or MCP calls. Declared limits are not measurements or safety approval.",
          "OFFLINE 전용: 트래픽, 장치 접속, DNS, 모델 또는 MCP 호출이 없습니다. 선언된 제한은 측정값이나 안전 승인이 아닙니다.",
        )}
      </Notice>
      {(pending || c.store.notice || c.error) && (
        <Panel title={t("Submission recovery", "제출 복구")}>
          {pending && (
            <>
              <p>
                {t(
                  "One saved request is held until an authoritative GET verifies it. Closing this page does not cancel the request or run.",
                  "권위 있는 GET으로 확인할 때까지 저장된 요청 하나를 유지합니다. 페이지를 닫아도 요청이나 실행이 취소되지 않습니다.",
                )}
              </p>
              <dl className="detail-list">
                <div>
                  <dt>{t("Request ID", "요청 ID")}</dt>
                  <dd className="mono">{pending.request.request_id}</dd>
                </div>
                <div>
                  <dt>
                    {t("Original scenario digest", "원본 시나리오 다이제스트")}
                  </dt>
                  <dd className="mono">{pending.request.scenario_digest}</dd>
                </div>
              </dl>
            </>
          )}
          {c.store.notice && (
            <Notice tone="warning">{errorText(locale, c.store.notice)}</Notice>
          )}
          {c.error && (
            <Notice tone="danger">{errorText(locale, c.error)}</Notice>
          )}
          <div className="runs-toolbar">
            <Button
              onClick={() => void c.recover()}
              disabled={!pending || c.busy}
            >
              {t("Retry saved request read", "저장된 요청 읽기 재시도")}
            </Button>
            <Button
              onClick={() => void c.replay()}
              disabled={!pending || c.busy || c.store.blocked}
            >
              {t("Retry identical saved request", "동일한 저장 요청 재시도")}
            </Button>
            <Button onClick={() => void c.recheck()} disabled={c.busy}>
              {t("Recheck recovery storage", "복구 저장소 다시 확인")}
            </Button>
            {pending?.checkpoint && (
              <Button onClick={() => show(pending.checkpoint!.run.id)}>
                {t("View pending run", "보류된 실행 보기")}
              </Button>
            )}
          </div>
        </Panel>
      )}
      {c.createdId && !pending && (
        <Notice>
          {t(
            "Submission verified. The run may continue independently.",
            "제출을 확인했습니다. 실행은 독립적으로 계속될 수 있습니다.",
          )}{" "}
          <Button onClick={() => show(c.createdId!)}>
            {t("View submitted run", "제출한 실행 보기")}
          </Button>
        </Notice>
      )}
      <div className="runs-layout">
        <Panel
          title={t("New OFFLINE preparation", "새 OFFLINE 준비")}
          description={t(
            "Use one immutable saved scenario version.",
            "저장된 불변 시나리오 버전 하나를 사용합니다.",
          )}
        >
          {sourceState === "loading" && (
            <p role="status">
              {t("Loading saved scenarios…", "저장된 시나리오 불러오는 중…")}
            </p>
          )}
          {sourceState === "error" && (
            <Notice tone="danger">
              {t(
                "Scenario source unavailable. New capture is disabled; existing runs remain independently readable.",
                "시나리오 원본을 사용할 수 없습니다. 새 캡처는 차단되지만 기존 실행은 독립적으로 읽을 수 있습니다.",
              )}
            </Notice>
          )}
          <form
            className="runs-form"
            onSubmit={(e) => {
              e.preventDefault();
              if (canStart) void c.submit(selected!);
            }}
          >
            <Field label={t("Saved scenario", "저장된 시나리오")}>
              <select
                value={scenarioId}
                disabled={sourceState !== "ready"}
                onChange={(e) => {
                  setScenarioId(e.target.value);
                  setHistory(null);
                  setHistoryState(e.target.value ? "loading" : "ready");
                }}
              >
                <option value="">
                  {t("Select a saved scenario", "저장된 시나리오 선택")}
                </option>
                {sources?.items.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.definition.name} · {s.id}
                  </option>
                ))}
              </select>
            </Field>
            {historyState === "loading" && (
              <p role="status">
                {t("Loading immutable history…", "불변 이력 불러오는 중…")}
              </p>
            )}
            {historyState === "error" && (
              <Notice tone="danger">
                {t(
                  "Scenario history could not be verified. Reload scenarios to retry.",
                  "시나리오 이력을 검증하지 못했습니다. 시나리오를 새로고침하여 재시도하세요.",
                )}
              </Notice>
            )}
            <Field label={t("Scenario version", "시나리오 버전")}>
              <select
                value={version}
                disabled={!history || historyState !== "ready"}
                onChange={(e) => setVersion(Number(e.target.value))}
              >
                {history?.versions.map((s) => (
                  <option key={s.version} value={s.version}>
                    {t("Version", "버전")} {s.version} · {s.created_at}
                  </option>
                ))}
              </select>
            </Field>
            <Field label={t("Task", "작업")}>
              <select value="offline_manifest_v1" disabled>
                <option>offline_manifest_v1</option>
              </select>
            </Field>
            {selected && (
              <p className="mono runs-identity">
                {selected.id} · v{selected.version}
                <br />
                {selected.digest}
              </p>
            )}
            <Button type="submit" variant="primary" disabled={!canStart}>
              {t("Start OFFLINE preparation", "OFFLINE 준비 시작")}
            </Button>
          </form>
          <div className="runs-toolbar">
            <Button
              disabled={sourceState === "loading"}
              onClick={() => {
                setSourceState("loading");
                setHistoryState(scenarioId ? "loading" : "ready");
                setSourceReload((n) => n + 1);
              }}
            >
              {t("Reload scenarios", "시나리오 새로고침")}
            </Button>
            <Button
              disabled={sourceState === "loading" || sourceOffset === 0}
              onClick={() => {
                setSourceState("loading");
                setScenarioId("");
                setHistory(null);
                setSourceOffset((n) => Math.max(0, n - 20));
              }}
            >
              {t("Previous scenarios", "이전 시나리오")}
            </Button>
            <Button
              disabled={
                sourceState !== "ready" ||
                !sources ||
                sourceOffset + 20 >= sources.total
              }
              onClick={() => {
                setSourceState("loading");
                setScenarioId("");
                setHistory(null);
                setSourceOffset((n) => n + 20);
              }}
            >
              {t("Next scenarios", "다음 시나리오")}
            </Button>
          </div>
          {sourceState === "ready" && sources?.total === 0 && (
            <EmptyState
              title={t("No saved scenarios", "저장된 시나리오 없음")}
              description={t(
                "Save a definition in the scenario library before preparing a run.",
                "실행 준비 전에 시나리오 라이브러리에 정의를 저장하세요.",
              )}
              action={
                <Button onClick={() => navigate("profiles")}>
                  {t("Open scenario library", "시나리오 라이브러리 열기")}
                </Button>
              }
            />
          )}
          {selected && (
            <details>
              <summary>
                {t(
                  "Inspect selected immutable version",
                  "선택한 불변 버전 확인",
                )}
              </summary>
              <ScenarioDetails record={selected} locale={locale} />
            </details>
          )}
        </Panel>
        <Panel title={t("Preparation, not evaluation", "평가가 아닌 준비")}>
          <div className="runs-boundary">
            <Badge tone="info">NOT_EVALUATED</Badge>
            <h3>{t("No defense verdict", "방어 판정 없음")}</h3>
            <p>
              {t(
                "Measurements and defense verdict remain null. No captured packets or device evidence have been ingested.",
                "측정값과 방어 판정은 null입니다. 캡처 패킷이나 장비 증거를 가져오지 않았습니다.",
              )}
            </p>
          </div>
          <p>
            {t(
              "The separate worker verifies the captured snapshot and compiles declared policy, limits and evidence requirements. It does not execute the scenario.",
              "별도 작업자가 캡처 스냅샷을 확인하고 선언된 정책, 제한 및 증거 요구사항을 정리합니다. 시나리오 자체를 실행하지 않습니다.",
            )}
          </p>
          <p className="muted">
            {t(
              "Up to 128 retained runs; 16 unfinished; two worker leases. Completed records are not deleted automatically.",
              "실행 128개 보관, 미완료 16개, 작업자 임대 2개 한도입니다. 완료된 기록을 자동으로 삭제하지 않습니다.",
            )}
          </p>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              show(directId);
            }}
            className="runs-form"
          >
            <Field label={t("Read a run by exact ID", "정확한 ID로 실행 읽기")}>
              <input
                value={directId}
                onChange={(e) => setDirectId(e.target.value)}
                spellCheck={false}
              />
            </Field>
            <Button type="submit">{t("Read run", "실행 읽기")}</Button>
          </form>
          {directInvalid && (
            <Notice tone="danger">
              {t(
                "Enter the original lowercase UUIDv4 run ID. No normalization is performed.",
                "원본 소문자 UUIDv4 실행 ID를 입력하세요. 자동 정규화하지 않습니다.",
              )}
            </Notice>
          )}
        </Panel>
      </div>
      <Panel
        title={t("Run history", "실행 이력")}
        actions={
          <Button onClick={refreshRuns} disabled={listState === "loading"}>
            <RefreshCw size={15} aria-hidden="true" />
            {t("Refresh runs", "실행 새로고침")}
          </Button>
        }
      >
        {listState === "loading" && (
          <p role="status">
            {t("Loading run history…", "실행 이력 불러오는 중…")}
          </p>
        )}
        {listState === "error" && (
          <Notice tone="danger">
            {errorText(locale, listError ?? "RUN_CLIENT_INVALID")}{" "}
            {list
              ? t(
                  "Displayed history is stale.",
                  "표시된 이력은 오래된 상태입니다.",
                )
              : t(
                  "Run history is unavailable, not empty.",
                  "실행 이력을 사용할 수 없습니다. 빈 이력이 아닙니다.",
                )}
          </Notice>
        )}
        {listState === "ready" && list?.total === 0 && (
          <EmptyState
            icon={<Activity size={26} />}
            title={t("No OFFLINE runs yet", "아직 OFFLINE 실행 없음")}
            description={t(
              "Start from a saved version. No traffic or measurements will be generated.",
              "저장된 버전으로 시작하세요. 트래픽이나 측정값은 생성되지 않습니다.",
            )}
          />
        )}
        {list && list.items.length > 0 && (
          <DataTable label={t("Retained OFFLINE runs", "보관된 OFFLINE 실행")}>
            <table className="runs-table">
              <thead>
                <tr>
                  <th>{t("Run / scenario", "실행 / 시나리오")}</th>
                  <th>{t("State", "상태")}</th>
                  <th>{t("Created / events", "생성 / 이벤트")}</th>
                </tr>
              </thead>
              <tbody>
                {list.items.map((run) => (
                  <tr key={run.id}>
                    <td>
                      <Button
                        variant="ghost"
                        onClick={(e) => {
                          invoker.current = e.currentTarget;
                          show(run.id, run);
                        }}
                      >
                        {run.id}
                      </Button>
                      <small className="mono">
                        {run.scenario_id} · v{run.scenario_version}
                      </small>
                    </td>
                    <td>
                      {term(locale, run.state)}
                      <small>{run.state}</small>
                      {run.failure_code && (
                        <small>{term(locale, run.failure_code)}</small>
                      )}
                    </td>
                    <td>
                      <time>{run.created_at}</time>
                      <small>
                        {run.event_count} {t("events", "이벤트")}
                      </small>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </DataTable>
        )}
        {list && (
          <div className="runs-toolbar">
            <span>
              {t("Retained membership", "보관 구성")} {list.after}–
              {list.items.at(-1)?.ordinal ?? list.after} / {list.total}
            </span>
            <Button
              disabled={listState === "loading" || list.after === 0}
              onClick={() => {
                setListState("loading");
                setPageRequest({
                  after: Math.max(0, list.after - 20),
                  through: list.through,
                  reload: pageRequest.reload,
                });
              }}
            >
              {t("Previous runs", "이전 실행")}
            </Button>
            <Button
              disabled={listState === "loading" || list.next_after === null}
              onClick={() => {
                setListState("loading");
                setPageRequest({
                  after: list.next_after!,
                  through: list.through,
                  reload: pageRequest.reload,
                });
              }}
            >
              {t("Next runs", "다음 실행")}
            </Button>
          </div>
        )}
      </Panel>
      {c.view && (
        <RunDetails
          key={c.view.token.description + ":" + c.view.id}
          controller={c}
          locale={locale}
          onClose={() => {
            c.leave();
            invoker.current?.focus();
          }}
        />
      )}
    </div>
  );
}
