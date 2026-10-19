import { useRef } from "react";
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
  const assignment = useRef<HTMLDetailsElement>(null);
  const viewSaved = () => {
    if (!assignment.current) return;
    assignment.current.open = true;
    assignment.current.querySelector<HTMLInputElement>("input")?.focus();
  };
  const t = (en: string, ko: string) => choose(locale, en, ko);
  return (
    <div className="page-stack ai-page">
      <PageHeader
        eyebrow={t("AI & governance", "AI 및 거버넌스")}
        title={t("Agent", "에이전트")}
        description={t(
          "Talk to your approved local model. Agent settings require explicit read/propose consent and separate exact write approval. Device actions remain unavailable.",
          "승인한 로컬 모델과 대화하세요. 에이전트 설정에는 명시적 읽기/제안 동의와 별도 저장 승인이 필요합니다. 장치 작업은 불가능합니다.",
        )}
        actions={
          <Button onClick={() => navigate("ai-settings")}>
            {t("AI settings", "AI 설정")}
          </Button>
        }
      />
      <ChatPanel
        locale={locale}
        mutationsEnabled={mutationsEnabled}
        onSaved={refresh}
        onViewSaved={viewSaved}
        onViewSkill={(expectation) =>
          navigate("skills", { id: expectation.skill.id, expectation })
        }
        onViewTarget={(expectation) =>
          navigate("targets", { id: expectation.target.id, expectation })
        }
      />
      {data && (
        <fieldset className="page-fieldset" disabled={!mutationsEnabled}>
          <details className="chat-assignment" ref={assignment}>
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
