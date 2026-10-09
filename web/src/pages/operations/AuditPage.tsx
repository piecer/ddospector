import { useState } from "react";
import { History } from "lucide-react";
import {
  Badge,
  Button,
  DataTable,
  Dialog,
  EmptyState,
  Field,
  Notice,
  PageHeader,
  Panel,
} from "../../components/ui";
import type { PageProps } from "../../lib/contracts";
import { choose, formatDate } from "../../lib/i18n";
import { RefreshWorkspace } from "./common";

export function AuditPage({ data, locale, navigate, refresh }: PageProps) {
  const t = (en: string, ko: string) => choose(locale, en, ko);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const normalizedQuery = query.trim().toLowerCase();
  const selected = data.audit.find((event) => event.id === selectedId);
  const events = data.audit
    .filter((event) =>
      [event.action, event.entity_id, event.id].some((value) =>
        value.toLowerCase().includes(normalizedQuery),
      ),
    )
    .sort(
      (a, b) =>
        (Date.parse(b.created_at) || 0) - (Date.parse(a.created_at) || 0),
    );
  return (
    <div className="page-stack operations-page">
      <PageHeader
        eyebrow={t("System / Local activity", "시스템 / 로컬 활동")}
        title={t("Audit log", "감사 이력")}
        description={t(
          "Inspect actual changes recorded by the local draft service.",
          "로컬 초안 서비스에 기록된 실제 변경을 확인합니다.",
        )}
      />
      <RefreshWorkspace locale={locale} refresh={refresh} />
      <Notice>
        {t(
          "Only events in the current snapshot are shown. This is not a lifetime history or a tamper-proof audit store.",
          "현재 스냅샷의 이벤트만 표시합니다. 전체 기간 이력이나 변조 방지 감사 저장소가 아닙니다.",
        )}
      </Notice>
      <Panel
        title={t("Draft activity", "초안 활동")}
        description={t(
          "Newest first. Timestamps use your browser’s local time; event details retain the original timestamp.",
          "최신순입니다. 시각은 브라우저의 현지 시간으로 표시하며, 이벤트 상세에는 원본 시각을 유지합니다.",
        )}
        actions={<Badge>{t("Local operator", "로컬 운영자")}</Badge>}
      >
        {data.audit.length > 0 && (
          <div className="operations-filter">
            <Field label={t("Search audit events", "감사 이벤트 검색")}>
              <input
                type="search"
                maxLength={200}
                value={query}
                placeholder={t(
                  "Action, entity, or event ID",
                  "작업, 개체 또는 이벤트 ID",
                )}
                onChange={(event) => setQuery(event.target.value)}
              />
            </Field>
            <div className="muted">
              <span className="mono">
                {events.length} / {data.audit.length}
              </span>
              <small>
                {t("Matched / loaded events", "검색 결과 / 불러온 이벤트")}
              </small>
            </div>
          </div>
        )}
        {data.audit.length === 0 ? (
          <EmptyState
            icon={<History size={32} />}
            title={t(
              "No draft activity recorded",
              "기록된 초안 활동이 없습니다",
            )}
            description={t(
              "Saving a target, campaign, Skill, or agent configuration creates real draft activity. Merely opening a page does not.",
              "대상, 캠페인, 스킬, 에이전트 구성을 저장하면 실제 초안 활동이 기록됩니다. 페이지를 여는 것만으로는 기록되지 않습니다.",
            )}
            action={
              <Button onClick={() => navigate("targets")}>
                {t("Configure the workspace", "워크스페이스 구성")}
              </Button>
            }
          />
        ) : events.length === 0 ? (
          <EmptyState
            title={t("No matching events", "일치하는 이벤트가 없습니다")}
            description={t(
              "Try an action, entity ID, or event ID from this loaded snapshot.",
              "현재 불러온 스냅샷의 작업, 개체 ID, 이벤트 ID로 검색하세요.",
            )}
            action={
              <Button onClick={() => setQuery("")}>
                {t("Clear search", "검색 지우기")}
              </Button>
            }
          />
        ) : (
          <DataTable
            label={t("Local draft audit events", "로컬 초안 감사 이벤트")}
          >
            <table className="table operations-table">
              <thead>
                <tr>
                  <th scope="col">{t("Timestamp", "시각")}</th>
                  <th scope="col">{t("Action", "작업")}</th>
                  <th scope="col">{t("Entity", "개체")}</th>
                  <th scope="col">{t("Origin", "출처")}</th>
                  <th scope="col">{t("Event ID", "이벤트 ID")}</th>
                </tr>
              </thead>
              <tbody>
                {events.map((event) => (
                  <tr key={event.id}>
                    <td>
                      <time dateTime={event.created_at}>
                        {formatDate(event.created_at, locale)}
                      </time>
                    </td>
                    <td>
                      <code>{event.action}</code>
                    </td>
                    <td className="mono">{event.entity_id}</td>
                    <td>{t("Local operator", "로컬 운영자")}</td>
                    <td>
                      <button
                        className="text-link mono operations-name"
                        type="button"
                        onClick={() => setSelectedId(event.id)}
                      >
                        {event.id}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </DataTable>
        )}
      </Panel>
      <div className="operations-footnote">
        <History size={16} aria-hidden="true" />
        <p>
          {t(
            "Draft audit events record configuration intent, not traffic, device access, or operational approval.",
            "초안 감사 이벤트는 구성 의도를 기록하며 트래픽, 장치 접속, 운영 승인을 의미하지 않습니다.",
          )}
        </p>
      </div>
      <Dialog
        open={Boolean(selected)}
        title={t("Audit event details", "감사 이벤트 상세")}
        onClose={() => setSelectedId(null)}
      >
        {selected && (
          <div className="form-stack">
            <dl className="detail-list">
              <dt>{t("Event ID", "이벤트 ID")}</dt>
              <dd className="mono">{selected.id}</dd>
              <dt>{t("Action", "작업")}</dt>
              <dd className="mono">{selected.action}</dd>
              <dt>{t("Entity ID", "개체 ID")}</dt>
              <dd className="mono">{selected.entity_id}</dd>
              <dt>{t("Original timestamp", "원본 시각")}</dt>
              <dd className="mono">{selected.created_at}</dd>
              <dt>{t("Origin", "출처")}</dt>
              <dd className="mono">{selected.origin}</dd>
            </dl>
            <Button onClick={() => setSelectedId(null)}>
              {t("Close", "닫기")}
            </Button>
          </div>
        )}
      </Dialog>
    </div>
  );
}
