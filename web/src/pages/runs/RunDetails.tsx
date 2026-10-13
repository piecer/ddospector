import { useEffect, useState } from "react";
import type { Locale } from "../../lib/contracts";
import { Badge, Button, Notice, Panel } from "../../components/ui";
import { choose } from "../../lib/i18n";
import { ScenarioDetails } from "../scenarios/ScenarioDetails";
import type { RunsController } from "./controller";
import type { EventPage } from "./types";
import { runAPI } from "./transport";
import { requireValue } from "./wire";
import { errorText, term } from "./labels";
export function RunDetails({
  controller: c,
  locale,
  onClose,
}: {
  controller: RunsController;
  locale: Locale;
  onClose: () => void;
}) {
  const t = (en: string, ko: string) => choose(locale, en, ko),
    v = c.view!,
    d = v.detail;
  const [events, setEvents] = useState<EventPage | null>(null),
    [eventError, setEventError] = useState(false),
    [reload, setReload] = useState(0);
  const id = v.id,
    count = d?.run.event_count;
  useEffect(() => {
    if (count === undefined) return;
    const abort = new AbortController();
    void runAPI.events(id, 0, 16, abort.signal).then(
      (page) => {
        if (abort.signal.aborted) return;
        try {
          const current = c.view?.detail;
          if (
            current?.run.id === id &&
            page.total === current.run.event_count
          ) {
            const last = page.items.at(-1)!;
            requireValue(
              last.state === current.run.state &&
                last.at === current.run.updated_at &&
                last.attempt === current.run.attempt &&
                last.generation === current.run.generation,
            );
            requireValue(page.items[0].at === current.run.created_at);
          }
          setEvents(page);
          setEventError(false);
        } catch {
          setEventError(true);
        }
      },
      () => {
        if (!abort.signal.aborted) setEventError(true);
      },
    );
    return () => abort.abort();
  }, [id, count, reload, c]);
  return (
    <Panel
      title={t("Run details", "실행 상세")}
      actions={
        <Button onClick={onClose}>{t("Close details", "상세 닫기")}</Button>
      }
    >
      <p className="mono runs-identity">{id}</p>
      {v.reading && (
        <p role="status">
          {t("Verifying captured run…", "캡처 실행 확인 중…")}
        </p>
      )}
      {v.error && (
        <Notice tone="danger">
          {errorText(locale, v.error)}{" "}
          {d
            ? t(
                "Last verified data retained — stale.",
                "마지막 검증 데이터를 보존했습니다 — 오래된 상태.",
              )
            : t("Details unavailable.", "상세 정보를 사용할 수 없습니다.")}
        </Notice>
      )}
      <div className="runs-toolbar">
        <Button
          className="runs-read-retry"
          onClick={() => {
            if (!v.reading && !v.cancelling) void c.read();
          }}
          aria-disabled={v.reading || v.cancelling}
        >
          {t("Retry run read", "실행 읽기 재시도")}
        </Button>
        <Button
          variant="danger"
          onClick={() => void c.cancel()}
          disabled={!v.canCancel || v.reading}
        >
          {v.cancelling
            ? t("Requesting cancellation…", "취소 요청 중…")
            : t("Cancel OFFLINE run", "OFFLINE 실행 취소")}
        </Button>
      </div>
      <p className="muted">
        {t(
          "Closing or navigating away stops observation only. It does not cancel the run. Observations are not proof of your original submission intent.",
          "닫기나 이동은 관찰만 중지합니다. 실행을 취소하지 않습니다. 관찰은 원래 제출 의도의 증명이 아닙니다.",
        )}
      </p>
      {performance.now() - v.started >= 300_000 && (
        <Notice tone="warning">
          {t(
            "Automatic observation budget ended. Read explicitly to check current state.",
            "자동 관찰 시간이 끝났습니다. 현재 상태를 명시적으로 읽으세요.",
          )}
        </Notice>
      )}
      {d && (
        <>
          <div className="runs-summary">
            <Badge
              tone={
                d.run.state === "SUCCEEDED"
                  ? "info"
                  : d.run.state === "FAILED"
                    ? "danger"
                    : "neutral"
              }
            >
              {d.run.state}
            </Badge>
            <h3>{term(locale, d.run.state)}</h3>
            {v.stale && <Badge tone="warning">{t("Stale", "오래됨")}</Badge>}
          </div>
          {d.run.failure_code && (
            <Notice tone="warning">
              {term(locale, d.run.failure_code)} · {d.run.failure_code}
            </Notice>
          )}
          <div className="runs-progress">
            <div>
              <small>{t("Claim attempts", "할당 시도")}</small>
              <strong>{d.run.attempt} / 3</strong>
            </div>
            <div>
              <small>{t("Fencing generation", "권한 세대")}</small>
              <strong>{d.run.generation}</strong>
            </div>
            <div>
              <small>{t("Durable events", "영속 이벤트")}</small>
              <strong>{d.run.event_count} / 16</strong>
            </div>
          </div>
          <dl className="detail-list">
            <div>
              <dt>{t("Request ID", "요청 ID")}</dt>
              <dd className="mono">{d.run.request_id}</dd>
            </div>
            <div>
              <dt>{t("Captured source revision", "캡처한 원본 리비전")}</dt>
              <dd>{d.snapshot.source_revision}</dd>
            </div>
            <div>
              <dt>{t("Snapshot digest", "스냅샷 다이제스트")}</dt>
              <dd className="mono">{d.snapshot.digest}</dd>
            </div>
            {(
              [
                ["created_at", "Created", "생성"],
                ["started_at", "First started", "첫 시작"],
                ["updated_at", "Updated", "갱신"],
                ["finished_at", "Finished", "종료"],
                ["deadline_at", "Absolute deadline", "절대 기한"],
                [
                  "cancel_requested_at",
                  "Cancellation requested at",
                  "취소 요청 시각",
                ],
              ] as const
            ).map(([key, en, ko]) => (
              <div key={key}>
                <dt>{t(en, ko)}</dt>
                <dd>{d.run[key] ?? t("Not observed", "관찰되지 않음")}</dd>
              </div>
            ))}
          </dl>
          {d.run.state === "CANCEL_REQUESTED" && (
            <Notice tone="warning">
              {t(
                "Durable cancellation intent, not proof that work has stopped.",
                "영속 취소 의도이며 작업 중지 증명은 아닙니다.",
              )}
            </Notice>
          )}
          {d.run.state === "CANCELLED" && (
            <Notice>
              {t(
                "Queued work was withdrawn or publication authority revoked/acknowledged; this is not a remote stop guarantee.",
                "대기 작업을 철회했거나 게시 권한을 철회·확인했습니다. 원격 중지 보장은 아닙니다.",
              )}
            </Notice>
          )}
          {d.result && (
            <section>
              <h3>
                {t(
                  "Compiled requirement manifest",
                  "작성된 요구사항 매니페스트",
                )}
              </h3>
              <p>
                {t(
                  "Defense not evaluated; measurements null; defense verdict null.",
                  "방어 미평가; 측정값 null; 방어 판정 null.",
                )}
              </p>
              <p>
                {term(locale, d.result.asset_status)} · {d.result.asset_status}
              </p>
              <ul>
                {d.result.evidence_requirements.map((e) => (
                  <li key={e.role}>
                    {e.role} — {t("Not ingested", "가져오지 않음")}{" "}
                    (NOT_INGESTED)
                  </li>
                ))}
              </ul>
              <p className="mono runs-identity">{d.result.digest}</p>
            </section>
          )}
          <section>
            <h3>{t("Ordered run events", "순서대로 기록된 실행 이벤트")}</h3>
            {eventError && (
              <Notice tone="danger">
                {t(
                  "Events unavailable. Any retained event page is stale; run details were not replaced.",
                  "이벤트를 사용할 수 없습니다. 보존된 이벤트 페이지는 오래되었으며 실행 상세는 교체하지 않았습니다.",
                )}
              </Notice>
            )}
            {!events && !eventError && (
              <p role="status">{t("Loading events…", "이벤트 불러오는 중…")}</p>
            )}
            <ol
              className="runs-timeline"
              aria-label={t(
                "Committed event timeline",
                "반영된 이벤트 타임라인",
              )}
            >
              {events?.items.map((e) => (
                <li key={e.seq}>
                  <strong>
                    {e.seq}. {term(locale, e.type)}
                  </strong>
                  <time>{e.at}</time>
                  <small>
                    {e.state} · {t("Attempt / generation", "시도 / 세대")}{" "}
                    {e.attempt} / {e.generation}
                  </small>
                  {e.reason && (
                    <p>
                      {term(locale, e.reason)} ({e.reason})
                    </p>
                  )}
                </li>
              ))}
            </ol>
            <Button onClick={() => setReload((n) => n + 1)}>
              {t("Reload events", "이벤트 새로고침")}
            </Button>
          </section>
          <details>
            <summary>
              {t(
                "Captured scenario and declared limits",
                "캡처 시나리오와 선언된 제한",
              )}
            </summary>
            <ScenarioDetails record={d.snapshot.scenario} locale={locale} />
          </details>
          <details>
            <summary>
              {t("Complete verified record (JSON)", "검증된 전체 기록 (JSON)")}
            </summary>
            <pre
              tabIndex={0}
              aria-label={t("Full verified record", "검증된 전체 기록")}
            >
              {JSON.stringify(d, null, 2)}
            </pre>
          </details>
        </>
      )}
    </Panel>
  );
}
