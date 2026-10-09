import { ScanSearch, Link2, Scale, Repeat2 } from "lucide-react";
import {
  Badge,
  Button,
  EmptyState,
  Notice,
  PageHeader,
  Panel,
} from "../../components/ui";
import type { PageProps } from "../../lib/contracts";
import { choose } from "../../lib/i18n";
import { LockedAction, RefreshWorkspace } from "./common";

export function FindingsPage({ locale, navigate, refresh }: PageProps) {
  const t = (en: string, ko: string) => choose(locale, en, ko);
  return (
    <div className="page-stack operations-page">
      <PageHeader
        eyebrow={t("Workspace / Analysis", "워크스페이스 / 분석")}
        title={t("Findings", "발견 사항")}
        description={t(
          "Review observed behavior against the intended defense policy.",
          "관찰된 동작을 의도한 방어 정책과 비교하여 검토합니다.",
        )}
        actions={
          <LockedAction
            label={t("Analyze evidence", "증거 분석")}
            reason={t(
              "Analysis requires run evidence. An empty list does not mean validation passed.",
              "실행 증거가 없어 분석할 수 없습니다. 발견 사항이 없다는 것은 검증을 통과했다는 뜻이 아닙니다.",
            )}
          />
        }
      />
      <RefreshWorkspace locale={locale} refresh={refresh} />
      <Notice tone="warning">
        <strong>
          {t(
            "Severity has not been assessed.",
            "심각도는 평가되지 않았습니다.",
          )}
        </strong>{" "}
        {t(
          "No detector or AI analysis is running in this offline workspace.",
          "이 오프라인 워크스페이스에서는 탐지기나 AI 분석이 실행되지 않습니다.",
        )}
      </Notice>
      <Panel
        title={t("Review queue", "검토 대기 목록")}
        actions={<Badge>{t("Awaiting evidence", "증거 대기")}</Badge>}
      >
        <EmptyState
          icon={<ScanSearch size={32} />}
          title={t("No findings to review", "검토할 발견 사항이 없습니다")}
          description={t(
            "Findings need an observed result, a baseline, and a traceable source. Campaign objectives and Skill instructions are not detections.",
            "발견 사항에는 관찰 결과, 기준값, 추적 가능한 출처가 필요합니다. 캠페인 목표와 스킬 지침은 탐지 결과가 아닙니다.",
          )}
          action={
            <Button onClick={() => navigate("evidence")}>
              {t("Open evidence workspace", "증거 워크스페이스 열기")}
            </Button>
          }
        />
      </Panel>
      <Panel
        title={t("Review criteria", "검토 기준")}
        description={t(
          "Requirements for future evidence-backed findings; no assessment has been performed.",
          "향후 증거 기반 발견 사항의 요건입니다. 평가는 수행되지 않았습니다.",
        )}
      >
        <div className="grid-three operations-criteria">
          <article>
            <Link2 size={21} aria-hidden="true" />
            <h3>{t("Traceable source", "추적 가능한 출처")}</h3>
            <p>
              {t(
                "Identify the run, target, and original artifact behind each observation.",
                "각 관찰의 근거가 된 실행, 대상, 원본 자료를 식별합니다.",
              )}
            </p>
          </article>
          <article>
            <Scale size={21} aria-hidden="true" />
            <h3>{t("Expected vs. observed", "기대 동작과 관찰 동작")}</h3>
            <p>
              {t(
                "Explain the policy expectation and measured deviation before assigning severity.",
                "심각도를 부여하기 전에 정책 기대치와 측정된 차이를 설명합니다.",
              )}
            </p>
          </article>
          <article>
            <Repeat2 size={21} aria-hidden="true" />
            <h3>{t("Repeatable review", "반복 가능한 검토")}</h3>
            <p>
              {t(
                "Retain scope, assumptions, and reviewer context with the evidence.",
                "증거와 함께 범위, 가정, 검토 맥락을 보관합니다.",
              )}
            </p>
          </article>
        </div>
      </Panel>
    </div>
  );
}
