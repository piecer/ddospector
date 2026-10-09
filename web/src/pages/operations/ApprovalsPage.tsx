import { ShieldCheck } from "lucide-react";
import {
  Badge,
  Button,
  DataTable,
  EmptyState,
  Notice,
  PageHeader,
  Panel,
} from "../../components/ui";
import type { PageProps } from "../../lib/contracts";
import { choose } from "../../lib/i18n";
import { LockedAction, RefreshWorkspace } from "./common";

export function ApprovalsPage({ data, locale, navigate, refresh }: PageProps) {
  const t = (en: string, ko: string) => choose(locale, en, ko);
  const boundaries = [
    {
      name: t("Local draft editing", "로컬 초안 편집"),
      available: data.capabilities.draft_editing,
      scope: t(
        "Configuration only; no execution authority.",
        "구성 전용이며 실행 권한은 없습니다.",
      ),
    },
    {
      name: t("Context preview", "컨텍스트 미리보기"),
      available: data.capabilities.context_preview,
      scope: t(
        "Deterministic instructions, not an AI response.",
        "결정론적 지침이며 AI 응답이 아닙니다.",
      ),
    },
    {
      name: t("Live execution", "라이브 실행"),
      available: data.capabilities.live_execution,
      scope: t(
        "Denied by the server in this stage.",
        "현재 단계에서 서버가 허용하지 않습니다.",
      ),
    },
    {
      name: t("MCP connection", "MCP 연결"),
      available: data.capabilities.mcp_connect,
      scope: t(
        "Registration stores a draft; no handshake.",
        "등록은 초안 저장이며 연결 협상은 수행하지 않습니다.",
      ),
    },
    {
      name: t("Model inference", "모델 추론"),
      available: data.capabilities.llm_inference,
      scope: t(
        "No model is called in this workspace.",
        "이 워크스페이스에서는 모델을 호출하지 않습니다.",
      ),
    },
  ];
  return (
    <div className="page-stack operations-page">
      <PageHeader
        eyebrow={t("AI & governance / Authority", "AI 및 거버넌스 / 권한")}
        title={t("Approvals", "승인")}
        description={t(
          "Keep planning permissions separate from operational authority.",
          "계획 권한과 운영 권한을 분리합니다.",
        )}
        actions={
          <LockedAction
            label={t("Approve execution", "실행 승인")}
            reason={t(
              "Operational approval and the safety gate are not implemented. This page cannot grant authority.",
              "운영 승인과 안전 게이트가 아직 구현되지 않았습니다. 이 화면에서는 권한을 부여할 수 없습니다.",
            )}
          />
        }
      />
      <RefreshWorkspace locale={locale} refresh={refresh} />
      <div className="operations-primary-grid">
        <Panel
          title={t("Approval queue", "승인 대기 목록")}
          actions={
            <Badge tone="warning">{t("Not implemented", "미구현")}</Badge>
          }
        >
          <EmptyState
            icon={<ShieldCheck size={32} />}
            title={t(
              "No operational approval requests",
              "운영 승인 요청이 없습니다",
            )}
            description={t(
              "Saving a campaign, assigning a Skill, or registering an MCP server never creates execution permission.",
              "캠페인 저장, 스킬 할당, MCP 서버 등록으로 실행 권한이 생성되지 않습니다.",
            )}
            action={
              <Button onClick={() => navigate("agent")}>
                {t("Review agent policy", "에이전트 정책 검토")}
              </Button>
            }
          />
        </Panel>
        <Panel title={t("Current agent authority", "현재 에이전트 권한")}>
          <dl className="detail-list operations-boundary">
            <dt>{t("Agent profile", "에이전트 프로필")}</dt>
            <dd className="operations-wrap">{data.agent_profile.name}</dd>
            <dt>{t("Autonomy", "자율성")}</dt>
            <dd>
              <Badge>{data.agent_profile.autonomy}</Badge>
            </dd>
            <dt>{t("Execution permission", "실행 권한")}</dt>
            <dd>{t("Not granted", "부여되지 않음")}</dd>
          </dl>
          <Notice>
            {t(
              "A Skill provides guidance, not permission.",
              "스킬은 지침을 제공하며 권한을 부여하지 않습니다.",
            )}
          </Notice>
        </Panel>
      </div>
      <Panel
        title={t("Capability boundaries", "기능 경계")}
        description={t(
          "Current server-reported capabilities. This is not an approval checklist.",
          "서버가 보고한 현재 기능입니다. 승인 점검표가 아닙니다.",
        )}
        actions={
          <Button variant="ghost" onClick={() => navigate("audit")}>
            {t("View audit history", "감사 이력 보기")}
          </Button>
        }
      >
        <DataTable label={t("Current capability boundaries", "현재 기능 경계")}>
          <table className="table operations-table">
            <thead>
              <tr>
                <th scope="col">{t("Capability", "기능")}</th>
                <th scope="col">{t("Availability", "가용 상태")}</th>
                <th scope="col">{t("Boundary", "경계")}</th>
              </tr>
            </thead>
            <tbody>
              {boundaries.map((boundary) => (
                <tr key={boundary.name}>
                  <th scope="row">{boundary.name}</th>
                  <td>
                    <Badge tone={boundary.available ? "info" : "neutral"}>
                      {boundary.available
                        ? t("Available", "사용 가능")
                        : t("Disabled", "비활성")}
                    </Badge>
                  </td>
                  <td>{boundary.scope}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </DataTable>
      </Panel>
    </div>
  );
}
