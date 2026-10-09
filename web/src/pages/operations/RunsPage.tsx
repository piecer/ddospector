import {
  Activity,
  FileCheck2,
  Gauge,
  ShieldCheck,
  Workflow,
} from "lucide-react";
import {
  Badge,
  Button,
  EmptyState,
  PageHeader,
  Panel,
} from "../../components/ui";
import type { PageProps } from "../../lib/contracts";
import { choose } from "../../lib/i18n";
import { LockedAction, RefreshWorkspace } from "./common";

export function RunsPage({ locale, navigate, refresh }: PageProps) {
  const t = (en: string, ko: string) => choose(locale, en, ko);
  return (
    <div className="page-stack operations-page">
      <PageHeader
        eyebrow={t("Workspace / Execution", "워크스페이스 / 실행")}
        title={t("Runs", "실행")}
        description={t(
          "Execution history belongs here. This workspace currently stores plans only.",
          "실행 이력을 확인하는 공간입니다. 현재 워크스페이스는 계획만 저장합니다.",
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
      <div className="operations-primary-grid">
        <Panel
          title={t("Run history", "실행 이력")}
          actions={
            <Badge tone="warning">{t("Execution locked", "실행 잠김")}</Badge>
          }
        >
          <EmptyState
            icon={<Activity size={32} />}
            title={t("No runs have been executed", "실행된 작업이 없습니다")}
            description={t(
              "No traffic, measurements, or run logs have been generated. Prepare a campaign draft without contacting any device.",
              "트래픽, 측정값, 실행 로그가 생성되지 않았습니다. 장치에 접속하지 않고 캠페인 초안을 준비할 수 있습니다.",
            )}
            action={
              <Button variant="primary" onClick={() => navigate("campaigns")}>
                {t("Prepare a campaign", "캠페인 준비")}
              </Button>
            }
          />
        </Panel>
        <Panel title={t("Execution boundary", "실행 경계")}>
          <dl className="detail-list operations-boundary">
            <dt>{t("Environment", "환경")}</dt>
            <dd>{t("Offline development", "오프라인 개발")}</dd>
            <dt>{t("Device contact", "장치 접속")}</dt>
            <dd>{t("Not available", "사용 불가")}</dd>
            <dt>{t("Runtime telemetry", "실행 텔레메트리")}</dt>
            <dd>{t("Not collected", "수집되지 않음")}</dd>
            <dt>{t("AI authority", "AI 권한")}</dt>
            <dd>{t("Review only", "검토 전용")}</dd>
          </dl>
          <Button variant="ghost" onClick={() => navigate("approvals")}>
            {t("Review safety boundaries", "안전 경계 확인")}
          </Button>
        </Panel>
      </div>
      <Panel
        title={t("Execution pipeline", "실행 파이프라인")}
        description={t(
          "Planned workflow, not live status.",
          "계획된 흐름이며 실시간 상태가 아닙니다.",
        )}
      >
        <ol
          className="operations-lifecycle"
          aria-label={t("Planned run lifecycle", "계획된 실행 수명주기")}
        >
          <li>
            <Workflow aria-hidden="true" size={22} />
            <h3>{t("Prepare", "준비")}</h3>
            <p>
              {t(
                "Describe the objective and select a lab target.",
                "목표를 정의하고 실험실 대상을 선택합니다.",
              )}
            </p>
          </li>
          <li>
            <ShieldCheck aria-hidden="true" size={22} />
            <h3>{t("Authorize", "승인")}</h3>
            <p>
              {t(
                "A future safety gate must admit the exact scope.",
                "향후 안전 게이트가 정확한 범위를 승인해야 합니다.",
              )}
            </p>
          </li>
          <li>
            <Gauge aria-hidden="true" size={22} />
            <h3>{t("Measure", "측정")}</h3>
            <p>
              {t(
                "Requires an implemented, authorized execution service.",
                "구현되고 승인된 실행 서비스가 필요합니다.",
              )}
            </p>
          </li>
          <li>
            <FileCheck2 aria-hidden="true" size={22} />
            <h3>{t("Review", "검토")}</h3>
            <p>
              {t(
                "Link findings to retained evidence, never assumptions.",
                "추정이 아닌 보관된 증거에 발견 사항을 연결합니다.",
              )}
            </p>
          </li>
        </ol>
      </Panel>
    </div>
  );
}
