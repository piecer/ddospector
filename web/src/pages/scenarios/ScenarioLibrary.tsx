import { useEffect, useRef, useState, type FormEvent } from "react";
import {
  Badge,
  Button,
  Dialog,
  Field,
  Notice,
  Panel,
} from "../../components/ui";
import type { PageProps } from "../../lib/contracts";
import { choose } from "../../lib/i18n";
import { scenarioAPI, ScenarioError } from "./client";
import type {
  ScenarioHistory,
  ScenarioPage,
  ScenarioReceipt,
  Submission,
} from "./types";
import {
  definitionFromDraft,
  draftFromDefinition,
  newDraft,
  type Draft,
} from "./draft";
import { ScenarioFields } from "./ScenarioFields";
import { ScenarioDetails } from "./ScenarioDetails";
import { canonical } from "./json";
import "./scenarios.css";
type Session = {
  draft: Draft;
  revision: number;
  opened: Submission["opened"];
  phase: "editing" | "saving" | "recovery";
  receipt?: ScenarioReceipt;
  error?: string;
  verified?: boolean;
};
export function ScenarioLibrary({
  data,
  locale,
  navigate,
}: Pick<PageProps, "data" | "locale" | "navigate">) {
  const c = (en: string, ko: string) => choose(locale, en, ko);
  const [page, setPage] = useState<ScenarioPage | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "error" | "stale">(
    "loading",
  );
  const [reload, setReload] = useState(0);
  const [offset, setOffset] = useState(0);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [historyId, setHistoryId] = useState("");
  const [history, setHistory] = useState<ScenarioHistory | null>(null);
  const [historyState, setHistoryState] = useState<
    "loading" | "ready" | "error"
  >("loading");
  const [version, setVersion] = useState(1);
  const historyRequest = useRef<AbortController | null>(null);
  const [session, setSession] = useState<Session | null>(null);
  const [editorOpen, setEditorOpen] = useState(false);
  const [validation, setValidation] = useState(false);
  const [saved, setSaved] = useState(false);
  // A read or a new draft cannot recover a storage failure observed this mount.
  const [storageBlocked, setStorageBlocked] = useState(false);
  const writing = useRef(false);
  const knownRevision = useRef(0);
  function observe(revision: number) {
    if (revision < knownRevision.current)
      throw new Error("Stale scenario read.");
    knownRevision.current = revision;
  }
  const operation = useRef<AbortController | null>(null);
  const [recovering, setRecovering] = useState(false);
  const readNavigationBlocked =
    !!session && (!storageBlocked || editorOpen || recovering);
  const ready =
    data.targets.some((t) => t.kind === "DUT") &&
    data.targets.some((t) => t.kind === "SINK");
  useEffect(() => {
    const controller = new AbortController();
    void scenarioAPI.read(offset, 50, controller.signal).then(
      (value) => {
        if (!controller.signal.aborted) {
          if (value.revision < knownRevision.current) setState("error");
          else {
            knownRevision.current = value.revision;
            setPage(value);
            setState("ready");
          }
        }
      },
      () => {
        if (!controller.signal.aborted) setState("error");
      },
    );
    return () => controller.abort();
  }, [reload, offset]);
  useEffect(
    () => () => {
      historyRequest.current?.abort();
      operation.current?.abort();
    },
    [],
  );
  async function showHistory(id: string) {
    historyRequest.current?.abort();
    const controller = new AbortController();
    historyRequest.current = controller;
    setHistoryId(id);
    setHistory(null);
    setHistoryOpen(true);
    setHistoryState("loading");
    try {
      const value = await scenarioAPI.history(id, controller.signal);
      if (!controller.signal.aborted) {
        observe(value.revision);
        const listed = page?.items.find((item) => item.id === id);
        if (
          listed &&
          !value.versions.some((item) => canonical(item) === canonical(listed))
        )
          throw new Error("Contradictory history.");
        setHistory(value);
        setVersion(value.versions.length);
        setHistoryState("ready");
      }
    } catch {
      if (!controller.signal.aborted) setHistoryState("error");
    }
  }
  function closeHistory() {
    historyRequest.current?.abort();
    setHistoryOpen(false);
  }
  function edit() {
    const selected = history?.versions[version - 1];
    if (
      storageBlocked ||
      !history ||
      !selected ||
      version !== history.versions.length ||
      version >= 10 ||
      !ready ||
      state !== "ready" ||
      session
    )
      return;
    closeHistory();
    setSession({
      draft: draftFromDefinition(selected.definition),
      revision: history.revision,
      opened: { id: selected.id, version },
      phase: "editing",
    });
    setEditorOpen(true);
    setValidation(false);
    setSaved(false);
  }
  function create() {
    if (
      storageBlocked ||
      !page ||
      state !== "ready" ||
      page.revision < knownRevision.current ||
      !ready ||
      session ||
      page.total >= 100
    )
      return;
    setSession({
      draft: newDraft(),
      revision: page.revision,
      opened: null,
      phase: "editing",
    });
    setEditorOpen(true);
    setValidation(false);
    setSaved(false);
  }
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (
      storageBlocked ||
      !session ||
      session.phase !== "editing" ||
      writing.current ||
      state !== "ready"
    )
      return;
    const definition = definitionFromDraft(session.draft);
    if (
      !definition ||
      !data.targets.some(
        (t) => t.id === definition.target_id && t.kind === "DUT",
      ) ||
      !data.targets.some(
        (t) => t.id === definition.sink_id && t.kind === "SINK",
      )
    ) {
      setValidation(true);
      return;
    }
    writing.current = true;
    setValidation(false);
    setSession({ ...session, phase: "saving" });
    const controller = new AbortController();
    operation.current = controller;
    let receipt: ScenarioReceipt | undefined,
      verified = false;
    try {
      receipt = await scenarioAPI.save(
        { revision: session.revision, definition, opened: session.opened },
        controller.signal,
      );
      observe((await scenarioAPI.verify(receipt, controller.signal)).revision);
      verified = true;
      const next = await scenarioAPI.read(offset, 50, controller.signal);
      observe(next.revision);
      setPage(next);
      setState("ready");
      setSaved(true);
      setSession(null);
      setEditorOpen(false);
    } catch (error) {
      if (!controller.signal.aborted) {
        // Only the mutation failure latches this observation, not GET readback.
        if (
          !receipt &&
          error instanceof ScenarioError &&
          (error.code === "SCENARIO_STATE_UNAVAILABLE" ||
            error.code === "SCENARIO_COMMIT_UNCERTAIN")
        )
          setStorageBlocked(true);
        setSession({
          ...session,
          phase: "recovery",
          receipt,
          verified,
          error: error instanceof ScenarioError ? error.code : "UNACKNOWLEDGED",
        });
        setState("stale");
      }
    } finally {
      writing.current = false;
    }
  }
  async function retryRecovery(discard = false) {
    if (!session || writing.current || session.phase === "saving") return;
    writing.current = true;
    setRecovering(true);
    const controller = new AbortController();
    operation.current = controller;
    try {
      if (!discard && session.receipt)
        observe(
          (await scenarioAPI.verify(session.receipt, controller.signal))
            .revision,
        );
      const next = await scenarioAPI.read(offset, 50, controller.signal);
      observe(next.revision);
      if (discard) {
        if (session.opened) {
          const current = await scenarioAPI.history(
            session.opened.id,
            controller.signal,
          );
          observe(current.revision);
          const latest = current.versions.at(-1)!;
          if (latest.version >= 10 || !ready) {
            setSession(null);
            setEditorOpen(false);
          } else
            setSession({
              draft: draftFromDefinition(latest.definition),
              revision: current.revision,
              opened: { id: latest.id, version: latest.version },
              phase: "editing",
            });
        } else if (next.total < 100 && ready)
          setSession({
            draft: newDraft(),
            revision: next.revision,
            opened: null,
            phase: "editing",
          });
        else {
          setSession(null);
          setEditorOpen(false);
        }
        setValidation(false);
      } else if (session.receipt) {
        setSaved(true);
        setSession(null);
        setEditorOpen(false);
      }
      // Without a valid receipt, reads cannot turn an ambiguous write into success.
      setPage(next);
      setState("ready");
    } catch {
      if (!controller.signal.aborted) setState("stale");
    } finally {
      writing.current = false;
      if (!controller.signal.aborted) setRecovering(false);
    }
  }
  const storageNotice = storageBlocked && (
    <Notice tone="warning">
      {c(
        "Scenario writes are blocked after a storage failure. Acknowledgement reads only check saved history; they do not recover storage or unlock writes. Operator storage recovery is required. Reloading this page only clears this UI observation; the API still decides whether writes are safe.",
        "저장소 오류로 시나리오 저장을 차단했습니다. 저장 확인 읽기는 저장된 이력만 확인하며 저장소를 복구하거나 저장 차단을 해제하지 않습니다. 운영자의 저장소 복구가 필요합니다. 페이지 전체 새로고침은 이 UI의 오류 관찰만 초기화하며, 저장 허용 여부는 API가 판단합니다.",
      )}
    </Notice>
  );
  return (
    <Panel
      className="scenario-library"
      title={c("Scenario library", "시나리오 라이브러리")}
      actions={
        <Button
          onClick={create}
          disabled={
            storageBlocked ||
            !ready ||
            state !== "ready" ||
            !!session ||
            !page ||
            page.revision < knownRevision.current ||
            page.total >= 100
          }
        >
          {c("New scenario", "새 시나리오")}
        </Button>
      }
    >
      <Notice>
        {c(
          "Definitions only. Registration is not approval; no execution, asset import or device verification occurs.",
          "정의만 기록합니다. 등록은 승인이 아니며 실행, 자산 가져오기 또는 장비 검증을 수행하지 않습니다.",
        )}
      </Notice>
      {storageNotice}
      {saved && (
        <p role="status">
          {c(
            "Scenario saved and verified in immutable history. No execution was started.",
            "불변 이력에서 시나리오 저장을 확인했습니다. 실행은 시작되지 않았습니다.",
          )}
        </p>
      )}
      {!ready && (
        <Notice tone="warning">
          {c(
            "Register a DUT and a different SINK before creating a scenario.",
            "시나리오 생성 전에 DUT와 별도의 수신 대상을 등록하세요.",
          )}
          <Button onClick={() => navigate("targets")}>
            {c("Configure scenario targets", "시나리오 대상 구성")}
          </Button>
        </Notice>
      )}
      {state === "loading" && (
        <p role="status">{c("Loading scenarios…", "시나리오 불러오는 중…")}</p>
      )}
      {state === "stale" && (
        <Notice tone="warning">
          {c(
            "The scenario library is stale. Resolve the preserved draft before another write.",
            "시나리오 라이브러리가 최신 상태가 아닙니다. 다른 저장 전에 보존된 초안을 확인하세요.",
          )}
        </Notice>
      )}
      {state === "error" && (
        <Notice tone="danger">
          {c(
            "The scenario library could not be read. Writes are disabled.",
            "시나리오 라이브러리를 읽지 못했습니다. 저장이 비활성화되었습니다.",
          )}
        </Notice>
      )}
      <Button
        disabled={state === "loading" || readNavigationBlocked}
        onClick={() => {
          setState("loading");
          setReload((n) => n + 1);
        }}
      >
        {state === "error"
          ? c("Retry read", "읽기 재시도")
          : c("Reload scenarios", "시나리오 새로고침")}
      </Button>
      {state === "ready" && page?.total === 0 && (
        <p>
          {c("No scenario definitions yet.", "아직 시나리오 정의가 없습니다.")}
        </p>
      )}
      {page && (state === "ready" || (storageBlocked && state === "stale")) && (
        <>
          <p>
            {c(
              `Showing ${page.items.length} of ${page.total} definitions · registry revision ${page.revision}`,
              `정의 ${page.total}개 중 ${page.items.length}개 · 레지스트리 리비전 ${page.revision}`,
            )}
          </p>
          {page.total >= 100 && (
            <Notice tone="warning">
              {c(
                "The limit of 100 scenario identities has been reached.",
                "시나리오 ID 100개 한도에 도달했습니다.",
              )}
            </Notice>
          )}
          <div className="scenario-list">
            {page.items.map((item) => (
              <article className="item-card" key={item.id}>
                <h3>{item.definition.name}</h3>
                <p className="mono">{item.id}</p>
                <Badge>
                  {c("Version ", "버전 ")}
                  {item.version}
                </Badge>
                <p>
                  {item.definition.dut_version} ·{" "}
                  {item.definition.policy_version}
                </p>
                <p>
                  {item.definition.expected_action} /{" "}
                  {item.definition.delivery_expectation}
                </p>
                <Button
                  disabled={readNavigationBlocked}
                  onClick={() => void showHistory(item.id)}
                >
                  {c("Scenario history", "시나리오 이력")}
                </Button>
              </article>
            ))}
          </div>
          <div className="button-row">
            <Button
              disabled={offset === 0 || readNavigationBlocked}
              onClick={() => {
                setState("loading");
                setOffset(offset - 50);
              }}
            >
              {c("Previous page", "이전 페이지")}
            </Button>
            <Button
              disabled={offset + 50 >= page.total || readNavigationBlocked}
              onClick={() => {
                setState("loading");
                setOffset(offset + 50);
              }}
            >
              {c("Next page", "다음 페이지")}
            </Button>
          </div>
        </>
      )}
      <Dialog
        open={historyOpen}
        title={c("Scenario history", "시나리오 이력")}
        onClose={closeHistory}
      >
        {storageNotice}
        {historyState === "loading" && (
          <p role="status">{c("Loading history…", "이력 불러오는 중…")}</p>
        )}
        {historyState === "error" && (
          <Notice tone="danger">
            {c(
              "History could not be read. Editing is disabled.",
              "이력을 읽지 못했습니다. 수정이 비활성화되었습니다.",
            )}
            <Button onClick={() => void showHistory(historyId)}>
              {c("Retry history read", "이력 읽기 재시도")}
            </Button>
          </Notice>
        )}
        {history && historyState === "ready" && (
          <div className="form-stack">
            <Field label={c("Revision", "리비전")}>
              <select
                value={version}
                onChange={(e) => setVersion(Number(e.target.value))}
              >
                {history.versions.map((item) => (
                  <option key={item.version} value={item.version}>
                    {c("Version ", "버전 ")}
                    {item.version}
                  </option>
                ))}
              </select>
            </Field>
            <ScenarioDetails
              record={history.versions[version - 1]}
              locale={locale}
            />
            {history.versions.length >= 10 && (
              <Notice tone="warning">
                {c(
                  "The limit of 10 immutable versions has been reached.",
                  "불변 버전 10개 한도에 도달했습니다.",
                )}
              </Notice>
            )}
            <Button
              disabled={
                storageBlocked ||
                !ready ||
                state !== "ready" ||
                version !== history.versions.length ||
                version >= 10 ||
                !!session
              }
              onClick={edit}
            >
              {c("Edit scenario", "시나리오 수정")}
            </Button>
          </div>
        )}
        <Button onClick={closeHistory}>{c("Close", "닫기")}</Button>
      </Dialog>
      {session && !editorOpen && (
        <Button onClick={() => setEditorOpen(true)}>
          {c("Review preserved draft", "보존된 초안 검토")}
        </Button>
      )}
      <Dialog
        open={editorOpen}
        recoveryOnly={storageBlocked || session?.phase === "recovery"}
        title={
          session?.opened
            ? c("Edit scenario", "시나리오 수정")
            : c("New scenario", "새 시나리오")
        }
        onClose={() => setEditorOpen(false)}
      >
        {session && (
          <form
            className="form-stack"
            noValidate
            onSubmit={submit}
            aria-busy={session.phase === "saving"}
          >
            {storageNotice}
            {validation && (
              <Notice tone="danger">
                {c(
                  "Check all required fields, integer bounds, targets and policy/evidence consistency. Your literal input is preserved.",
                  "필수 필드, 정수 범위, 대상 및 정책·증거 일치 여부를 확인하세요. 입력 원문을 보존합니다.",
                )}
              </Notice>
            )}
            {session.phase !== "editing" && (
              <Notice tone="warning">
                {c(
                  "Writes are disabled. Closing does not cancel a request already sent; the draft is preserved for review.",
                  "저장이 비활성화되었습니다. 닫아도 이미 보낸 요청은 취소되지 않으며 검토용 초안을 보존합니다.",
                )}
              </Notice>
            )}
            <p>
              {c(
                `Opening registry revision: ${session.revision}`,
                `열 때의 레지스트리 리비전: ${session.revision}`,
              )}
            </p>
            {session.phase === "recovery" && (
              <Notice tone="danger">
                <p>
                  {session.verified
                    ? c(
                        "The save was verified in history, but navigation could not be refreshed.",
                        "이력에서 저장을 확인했지만 목록을 새로고침하지 못했습니다.",
                      )
                    : session.error === "SCENARIO_CONFLICT"
                      ? c(
                          "Registry changed. This draft keeps its original revision; no automatic rebase or resubmission.",
                          "레지스트리가 변경되었습니다. 초안의 원래 리비전을 유지하며 자동 갱신이나 재전송을 하지 않습니다.",
                        )
                      : c(
                          "Save is not acknowledged. The draft is read-only; an uncertain write may have committed. Review or copy it before explicitly discarding it.",
                          "저장 확인이 완료되지 않았습니다. 초안은 읽기 전용이며 불확실한 저장이 반영되었을 수 있습니다. 명시적으로 버리기 전에 검토하거나 복사하세요.",
                        )}
                </p>
                <div className="button-row">
                  <Button
                    disabled={recovering}
                    onClick={() => void retryRecovery()}
                  >
                    {c("Retry acknowledgement read", "저장 확인 읽기 재시도")}
                  </Button>
                  <Button
                    disabled={recovering}
                    onClick={() => void retryRecovery(true)}
                  >
                    {c("Discard draft and reopen", "초안 버리고 다시 열기")}
                  </Button>
                </div>
              </Notice>
            )}
            <ScenarioFields
              draft={session.draft}
              change={(draft) => {
                if (
                  !storageBlocked &&
                  session.phase === "editing" &&
                  !writing.current
                )
                  setSession({ ...session, draft });
              }}
              targets={data.targets}
              locale={locale}
              locked={storageBlocked || session.phase !== "editing"}
            />
            <div className="button-row">
              <Button
                variant="primary"
                type="submit"
                disabled={
                  storageBlocked ||
                  session.phase !== "editing" ||
                  state !== "ready"
                }
              >
                {session.opened
                  ? c("Save new version", "새 버전 저장")
                  : c("Save scenario", "시나리오 저장")}
              </Button>
              <Button onClick={() => setEditorOpen(false)}>
                {c("Close", "닫기")}
              </Button>
              {session.phase === "editing" && (
                <Button
                  onClick={() => {
                    setSession(null);
                    setEditorOpen(false);
                  }}
                >
                  {c("Discard draft", "초안 버리기")}
                </Button>
              )}
            </div>
          </form>
        )}
      </Dialog>
    </Panel>
  );
}
