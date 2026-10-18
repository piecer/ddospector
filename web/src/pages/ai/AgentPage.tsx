import type { PageProps } from "../../lib/contracts";
import { choose } from "../../lib/i18n";
import { Button, PageHeader } from "../../components/ui";
import { AgentAssignmentPanel } from "./AgentAssignmentPanel";
import { ChatPanel } from "./ChatPanel";
import "./ai.css";
export function AgentPage({
  data,
  locale,
  navigate,
  refresh,
  mutationsEnabled = true,
}: Omit<PageProps, "data"> & {
  data?: PageProps["data"] | null;
  mutationsEnabled?: boolean;
}) {
  const t = (en: string, ko: string) => choose(locale, en, ko);
  return (
    <div className="page-stack ai-page">
      <PageHeader
        eyebrow={t("AI & governance", "AI 및 거버넌스")}
        title={t("Agent", "에이전트")}
        description={t(
          "Talk to your approved local model. Settings and device actions remain outside chat authority.",
          "승인한 로컬 모델과 대화하세요. 대화에는 설정 변경이나 장치 작업 권한이 없습니다.",
        )}
        actions={
          <Button onClick={() => navigate("ai-settings")}>
            {t("AI settings", "AI 설정")}
          </Button>
        }
      />
      <ChatPanel locale={locale} mutationsEnabled={mutationsEnabled} />
      {data && (
        <fieldset className="page-fieldset" disabled={!mutationsEnabled}>
          <details className="chat-assignment">
            <summary>
              {t(
                "Assignment and deterministic preview",
                "할당 및 결정적 미리보기",
              )}
            </summary>
            <AgentAssignmentPanel
              data={data}
              locale={locale}
              navigate={navigate}
              refresh={refresh}
            />
          </details>
        </fieldset>
      )}
    </div>
  );
}
