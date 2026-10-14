import { useEffect, useRef, useState } from "react";
import {
  Badge,
  Button,
  Field,
  Notice,
  PageHeader,
  Panel,
} from "../../components/ui";
import type { PageProps } from "../../lib/contracts";
import { choose } from "../../lib/i18n";
import { RefreshWorkspace } from "./common";
import { EvidenceController, type State } from "../evidence/controller";
import { evidenceAPI, loadSample, admitFile } from "../evidence/client";
import { download, exportReport, rows } from "../evidence/export";
import { errorText, label, status, warning } from "../evidence/labels";
import { sampleCatalog } from "../evidence/catalog";
import type { Side } from "../evidence/types";
import "../evidence/evidence.css";

export function EvidencePage({ locale, navigate, refresh }: PageProps) {
  const t = (en: string, ko: string) => choose(locale, en, ko);
  const controller = useRef<EvidenceController | null>(null);
  const [state, setState] = useState<State | null>(null);
  const [runId, setRunId] = useState("");
  const [files, setFiles] = useState<Partial<Record<Side, File>>>({});
  const [sample, setSample] =
    useState<(typeof sampleCatalog)[number]["sample_id"]>("complete");
  const [localBusy, setLocalBusy] = useState(false);
  const [localError, setLocalError] = useState(false);
  const task = useRef<AbortController | null>(null);
  const retire = useRef<(() => void) | null>(null);
  const mounted = useRef(false);
  useEffect(() => {
    mounted.current = true;
    const c = new EvidenceController();
    controller.current = c;
    setState(c.state);
    const unsub = c.subscribe(() => setState(c.state));
    void c.refreshList();
    void c.refreshRuns();
    return () => {
      mounted.current = false;
      unsub();
      c.dispose();
      task.current?.abort();
      retire.current?.();
      controller.current = null;
    };
  }, []);
  const blocked =
    !state || state.busy || !!state.pending || state.storageError || localBusy;
  async function localAction(work: (signal: AbortSignal) => Promise<void>) {
    if (task.current) return;
    const a = new AbortController();
    task.current = a;
    setLocalBusy(true);
    setLocalError(false);
    try {
      await work(a.signal);
    } catch {
      if (mounted.current && !a.signal.aborted) setLocalError(true);
    } finally {
      if (task.current === a) task.current = null;
      if (mounted.current) setLocalBusy(false);
    }
  }
  function save(value: string | Uint8Array, type: string, name: string) {
    retire.current?.();
    retire.current = download(value, type, name);
  }
  function pick(side: Side, f: File | undefined) {
    if (blocked) return;
    setLocalError(false);
    try {
      if (f) admitFile(f);
      setFiles((prev) => ({ ...prev, [side]: f }));
    } catch {
      setFiles((prev) => ({ ...prev, [side]: undefined }));
      setLocalError(true);
    }
  }
  const detail = state?.detail,
    report = detail?.report;
  return (
    <div className="page-stack operations-page evidence-page">
      <PageHeader
        eyebrow={t(
          "Workspace / OFFLINE artifacts",
          "워크스페이스 / OFFLINE 자료",
        )}
        title={t("Evidence", "증거")}
        description={t(
          "Register paired originals and inspect one retained capture criterion. No traffic, worker or evaluation is launched here.",
          "원본 쌍을 등록하고 보관된 캡처 단일 기준을 확인합니다. 여기서는 트래픽, 워커 또는 평가를 시작하지 않습니다.",
        )}
      />
      <Notice tone="warning">{warning(locale)}</Notice>
      <RefreshWorkspace locale={locale} refresh={refresh} />
      <Panel
        title={t("Register paired evidence", "증거 쌍 등록")}
        description={t(
          "Only completed OFFLINE preparation Runs. Two explicit roles; no automatic swapping.",
          "완료된 OFFLINE 준비 실행만 선택할 수 있습니다. 두 역할을 명시하며 자동으로 바꾸지 않습니다.",
        )}
      >
        <form
          className="form-stack"
          onSubmit={(event) => {
            event.preventDefault();
            if (!blocked && files.ingress && files.egress)
              void controller.current?.submit(
                runId,
                files.ingress,
                files.egress,
              );
          }}
        >
          <Field
            label={t("Completed OFFLINE Run", "완료된 OFFLINE 실행")}
            hint={t(
              "Full identifiers are shown. No Run or worker is started.",
              "전체 식별값을 표시합니다. 실행이나 워커를 시작하지 않습니다.",
            )}
          >
            <select
              value={runId}
              disabled={blocked || !!state?.runError}
              onChange={(e) => setRunId(e.target.value)}
              required
            >
              <option value="">
                {t("Select a completed Run", "완료된 실행 선택")}
              </option>
              {state?.runs?.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.id}
                </option>
              ))}
            </select>
          </Field>
          {runId && <p className="mono">{runId}</p>}
          {state?.runError && (
            <Notice tone="danger">{errorText(state.runError, locale)}</Notice>
          )}
          {state?.runs?.length === 0 && !state.runError && (
            <p>
              {t(
                "No completed OFFLINE Runs. Complete preparation explicitly in the Run workspace.",
                "완료된 OFFLINE 실행이 없습니다. 실행 워크스페이스에서 준비를 명시적으로 완료하세요.",
              )}
            </p>
          )}
          <div className="button-row">
            <Button
              onClick={() => void controller.current?.refreshRuns()}
              disabled={state?.busy}
            >
              {t("Refresh Runs", "실행 새로고침")}
            </Button>
            <Button variant="ghost" onClick={() => navigate("runs")}>
              {t("Open run workspace", "실행 워크스페이스 열기")}
            </Button>
          </div>
          <div className="evidence-pair">
            {(["ingress", "egress"] as const).map((side) => (
              <div key={side}>
                <Field
                  label={
                    side === "ingress"
                      ? t("Ingress PCAP", "유입 PCAP")
                      : t("Egress PCAP", "유출 PCAP")
                  }
                  hint={t(
                    "1–65,536 bytes; filename 1–128 code points and ≤256 UTF-8 bytes. Original name preserved.",
                    "1–65,536바이트; 파일명 1–128 코드 포인트, UTF-8 256바이트 이하. 원래 이름을 보존합니다.",
                  )}
                >
                  <input
                    type="file"
                    disabled={blocked}
                    onChange={(e) => pick(side, e.target.files?.[0])}
                  />
                </Field>
                <p className="evidence-literal">
                  {files[side]
                    ? `${files[side]!.name} · ${files[side]!.size} bytes`
                    : t("No file selected", "선택된 파일 없음")}
                </p>
              </div>
            ))}
          </div>
          {state?.storageError && (
            <Notice tone="danger">
              {t(
                "Pending identity storage is unavailable or invalid. Uploads and resolution are locked; do not discard an unresolved request or resend it.",
                "대기 요청 식별값 저장소를 사용할 수 없거나 올바르지 않습니다. 업로드와 조회를 잠급니다. 미해결 요청을 버리거나 재전송하지 마세요.",
              )}
            </Notice>
          )}
          {state?.pending && (
            <Notice tone="warning">
              <div>
                <p>
                  {t(
                    "Acknowledgement unresolved. Keep this request ID; only read-only resolution is offered. A 404 is not proof the POST cannot later commit.",
                    "응답 확인이 미해결 상태입니다. 요청 ID를 유지하세요. 읽기 전용 조회만 제공합니다. 404는 POST가 나중에 커밋되지 않는다는 증거가 아닙니다.",
                  )}
                </p>
                <p className="mono">{state.pending.request_id}</p>
                <Button
                  disabled={state.busy || state.storageError}
                  onClick={() => void controller.current?.resolve()}
                >
                  {t(
                    "Resolve by request ID (GET only)",
                    "요청 ID로 확인 (GET만)",
                  )}
                </Button>
              </div>
            </Notice>
          )}
          {state?.actionError && (
            <Notice tone="danger">
              {errorText(state.actionError, locale)}
            </Notice>
          )}
          {state?.registered && (
            <p role="status">
              {t(
                "Originals registered and acknowledgement verified. No evaluation was started.",
                "원본 등록 및 응답 바인딩을 검증했습니다. 평가를 시작하지 않았습니다.",
              )}
            </p>
          )}
          <Button
            variant="primary"
            type="submit"
            disabled={
              blocked ||
              !runId ||
              !files.ingress ||
              !files.egress ||
              !!state?.runError
            }
          >
            {state?.busy
              ? t("Registering / resolving…", "등록 / 조회 중…")
              : t("Register originals", "원본 등록")}
          </Button>
        </form>
      </Panel>
      <Panel
        title={t("Synthetic sample pairs", "합성 샘플 쌍")}
        description={t(
          "Real generated PCAP files, not captured DUT traffic or full sessions. Sample names and manifest expectations are never analysis results. Selecting a pair never uploads it.",
          "실제 생성된 PCAP 파일이며 DUT 트래픽 캡처나 전체 세션이 아닙니다. 샘플명과 매니페스트 기대값은 분석 결과가 아닙니다. 쌍 선택만으로 업로드하지 않습니다.",
        )}
      >
        <div className="evidence-sample-controls">
          <Field label={t("Sample pair", "샘플 쌍")}>
            <select
              disabled={blocked}
              value={sample}
              onChange={(e) => setSample(e.target.value as typeof sample)}
            >
              {sampleCatalog.map((x) => (
                <option key={x.sample_id}>{x.sample_id}</option>
              ))}
            </select>
          </Field>
          <div className="button-row">
            <Button
              disabled={blocked}
              onClick={() =>
                void localAction(async (signal) => {
                  const pair = await loadSample(sample, signal);
                  signal.throwIfAborted();
                  if (mounted.current) setFiles(pair);
                })
              }
            >
              {t("Use sample pair in form", "샘플 쌍을 양식에 넣기")}
            </Button>
            {(["ingress", "egress"] as const).map((side) => (
              <Button
                key={side}
                disabled={blocked}
                onClick={() =>
                  void localAction(async (signal) => {
                    const pair = await loadSample(sample, signal);
                    const bytes = new Uint8Array(
                      await pair[side].arrayBuffer(),
                    );
                    signal.throwIfAborted();
                    save(bytes, "application/octet-stream", pair[side].name);
                  })
                }
              >
                {side === "ingress"
                  ? t("Download sample ingress", "유입 샘플 다운로드")
                  : t("Download sample egress", "유출 샘플 다운로드")}
              </Button>
            ))}
          </div>
        </div>
      </Panel>
      {localError && (
        <Notice tone="danger">
          {t(
            "File, download or export validation failed. Check the 1–65,536 byte limit, exact filename rules and integrity. Nothing was silently truncated.",
            "파일, 다운로드 또는 내보내기 검증에 실패했습니다. 1–65,536바이트 제한, 정확한 파일명 규칙 및 무결성을 확인하세요. 데이터를 잘라내지 않았습니다.",
          )}
        </Notice>
      )}
      <Panel
        title={t("Artifact repository", "자료 저장소")}
        actions={
          <Button onClick={() => void controller.current?.refreshList()}>
            {t("Refresh repository", "저장소 새로고침")}
          </Button>
        }
      >
        {state?.listError && (
          <Notice tone="danger">{errorText(state.listError, locale)}</Notice>
        )}
        {!state?.collection && !state?.listError && (
          <p>{t("Loading repository…", "저장소 불러오는 중…")}</p>
        )}
        {state?.collection && (
          <>
            <p>
              {state.listError
                ? t("Stale repository snapshot", "오래된 저장소 스냅샷")
                : t(
                    "Validated repository metadata",
                    "검증된 저장소 메타데이터",
                  )}{" "}
              · {state.collection.total}/16
            </p>
            {state.collection.total === 0 && !state.listError && (
              <p>{t("No retained evidence.", "보관된 증거가 없습니다.")}</p>
            )}
            <ol className="evidence-repository">
              {state.collection.items.map((s) => (
                <li key={s.id}>
                  <Button
                    className="evidence-choice"
                    disabled={localBusy}
                    aria-pressed={state.selected === s.id}
                    onClick={() => void controller.current?.select(s.id)}
                  >
                    #{s.ordinal} {s.id}
                  </Button>
                  <p>
                    {status(s.analysis_state, locale)} · {s.provenance} ·{" "}
                    {s.coverage}
                  </p>
                  <p className="evidence-literal">
                    {s.ingress.name} → {s.egress.name}
                  </p>
                </li>
              ))}
            </ol>
          </>
        )}
      </Panel>
      {state?.selected && (
        <Panel
          title={t("Selected evidence", "선택된 증거")}
          actions={
            <Button
              disabled={localBusy}
              onClick={() => void controller.current?.refreshSelected()}
            >
              {t("Refresh selected", "선택 항목 새로고침")}
            </Button>
          }
        >
          <p className="mono">{state.selected}</p>
          {state.readError && (
            <Notice tone="danger">{errorText(state.readError, locale)}</Notice>
          )}
          {state.waiting && (
            <div className="button-row">
              <p role="status">
                {t(
                  "Waiting for a retained result · GET only, every 2 seconds after completion, at most 60 seconds.",
                  "보관 결과를 기다리는 중 · GET만 사용하며 완료 후 2초마다, 최대 60초 조회합니다.",
                )}
              </p>
              <Button onClick={() => controller.current?.stopPolling()}>
                {t("Stop waiting", "대기 중지")}
              </Button>
            </div>
          )}
          {state.pollStopped && (
            <p>
              {t(
                "Automatic waiting stopped. Manual refresh is available.",
                "자동 대기가 중지되었습니다. 수동 새로고침을 사용할 수 있습니다.",
              )}
            </p>
          )}
          {detail && (
            <div className="form-stack">
              <Notice tone="warning">
                {t(
                  "NOT_EVALUATED / defense_verdict: null — OFFLINE preparation, not DUT/service/session success. UNKNOWN is inconclusive, never block success.",
                  "NOT_EVALUATED / defense_verdict: null — OFFLINE 준비이며 DUT/서비스/세션 성공이 아닙니다. UNKNOWN은 결론 불가이며 차단 성공이 아닙니다.",
                )}
              </Notice>
              <div className="chips">
                <Badge tone="warning">{detail.evidence.provenance}</Badge>
                <Badge>{detail.evidence.coverage}</Badge>
                <Badge>{status(detail.evidence.analysis_state, locale)}</Badge>
              </div>
              {report ? (
                <>
                  <h2>{status(report.outcome, locale)}</h2>
                  <p>
                    {t(
                      "Observed matched / missing ingress records",
                      "관측 일치 / 유입 누락 레코드",
                    )}
                    : {report.facts?.matched_packets ?? "null"} /{" "}
                    {report.facts?.unmatched_ingress_packets ?? "null"} ·{" "}
                    {t("Snapshot delivery thresholds", "스냅샷 전달 임계값")}:{" "}
                    {report.policy.minimum_delivery_pct}–
                    {report.policy.maximum_delivery_pct}%
                  </p>
                  <p>
                    {t(
                      "Producer start time (not capture/completion time)",
                      "생산자 시작 시각 (캡처/완료 시각 아님)",
                    )}
                    : <span className="mono">{report.created_at}</span>
                  </p>
                  <p>
                    {t("Unassessed requirements", "미평가 요건")}:{" "}
                    {report.unassessed_requirements.join(", ")}
                  </p>
                  <div className="button-row">
                    {(["json", "html"] as const).map((format) => (
                      <Button
                        key={format}
                        disabled={localBusy || !!state.readError}
                        onClick={() =>
                          void localAction(async (signal) => {
                            const result = await exportReport(
                              detail,
                              state.source!,
                              locale,
                            );
                            signal.throwIfAborted();
                            save(
                              result[format],
                              format === "json"
                                ? "application/json"
                                : "text/html",
                              `${detail.evidence.id}-${locale}.${format}`,
                            );
                          })
                        }
                      >
                        {format === "json"
                          ? t("Export JSON", "JSON 내보내기")
                          : t("Export HTML", "HTML 내보내기")}
                      </Button>
                    ))}
                  </div>
                </>
              ) : (
                <>
                  <h2>{t("Registered · unassessed", "등록됨 · 미평가")}</h2>
                  <p>
                    {t(
                      "Evaluate manually in your explicitly owned workspace. /your/workspace is a placeholder. No HTTP evaluation button or automatic worker.",
                      "명시적으로 소유한 워크스페이스에서 수동 평가하세요. /your/workspace는 자리표시자입니다. HTTP 평가 버튼이나 자동 워커는 없습니다.",
                    )}
                  </p>
                  <code className="evidence-command">
                    make phase2-evaluate WORKSPACE=/your/workspace EVIDENCE_ID=
                    {detail.evidence.id}
                  </code>
                </>
              )}
              <div className="button-row">
                {(["ingress", "egress"] as const).map((side) => (
                  <Button
                    key={side}
                    disabled={localBusy || !!state.readError}
                    onClick={() =>
                      void localAction(async (signal) => {
                        const bytes = await evidenceAPI.raw(
                          detail.evidence,
                          side,
                          signal,
                        );
                        signal.throwIfAborted();
                        save(
                          bytes,
                          "application/octet-stream",
                          `${detail.evidence.id}-${side}.pcap`,
                        );
                      })
                    }
                  >
                    {side === "ingress"
                      ? t("Download original ingress", "유입 원본 다운로드")
                      : t("Download original egress", "유출 원본 다운로드")}
                  </Button>
                ))}
              </div>
              <h3>
                {t(
                  "Original identities and retained facts",
                  "원본 식별값 및 보관 사실",
                )}
              </h3>
              <dl className="evidence-facts">
                {rows(
                  {
                    evidence: detail.evidence,
                    ...(report ? { report } : {}),
                    ...(state.source?.result
                      ? { declared_limits: state.source.result.declared_limits }
                      : {}),
                  },
                  locale,
                ).map((r) => (
                  <div key={r.key}>
                    <dt>{r.title}</dt>
                    <dd>{r.value}</dd>
                  </div>
                ))}
              </dl>
              {!report && state.source && (
                <p>
                  {label("unassessed_requirements", locale)}:{" "}
                  {state.source.snapshot.scenario.definition.evidence_requirements.join(
                    ", ",
                  )}
                </p>
              )}
            </div>
          )}
        </Panel>
      )}
      <Panel title={t("Drafts ≠ evidence", "초안과 증거는 다릅니다")}>
        <p>
          {t(
            "Local drafts are not execution evidence.",
            "로컬 초안은 실행 증거가 아닙니다.",
          )}
        </p>
        <Button variant="ghost" onClick={() => navigate("audit")}>
          {t("View draft audit history", "초안 감사 이력 보기")}
        </Button>
      </Panel>
    </div>
  );
}
