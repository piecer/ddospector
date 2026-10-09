import { useRef, useState } from "react";
import { ArrowRight, RefreshCw } from "lucide-react";
import {
  Badge,
  Button,
  DataTable,
  Notice,
  PageHeader,
  Panel,
} from "../../components/ui";
import type { PageProps } from "../../lib/contracts";
import { choose } from "../../lib/i18n";

export function SettingsPage({ data, locale, refresh, navigate }: PageProps) {
  const c = (en: string, ko: string) => choose(locale, en, ko);
  const lock = useRef(false);
  const [state, setState] = useState<"idle" | "loading" | "error" | "success">(
    "idle",
  );
  async function reload() {
    if (lock.current) return;
    lock.current = true;
    setState("loading");
    try {
      await refresh();
      setState("success");
    } catch {
      setState("error");
    } finally {
      lock.current = false;
    }
  }
  const capabilities = [
    {
      name: c("Draft editing", "초안 편집"),
      available: data.capabilities.draft_editing,
      detail: c(
        "Local metadata only; no operational side effects.",
        "로컬 메타데이터만 편집하며 운영 동작은 수행하지 않습니다.",
      ),
    },
    {
      name: c("Context preview", "맥락 미리보기"),
      available: data.capabilities.context_preview,
      detail: c(
        "Deterministic instruction assembly, not an AI response.",
        "지침을 결정적으로 구성하며 AI 응답을 생성하지 않습니다.",
      ),
    },
    {
      name: c("Live execution", "실제 실행"),
      available: data.capabilities.live_execution,
      detail: c(
        "The API does not admit live runs.",
        "API가 실제 실행을 허용하지 않습니다.",
      ),
    },
    {
      name: c("MCP connection", "MCP 연결"),
      available: data.capabilities.mcp_connect,
      detail: c(
        "No server handshake, tool discovery, or device control.",
        "서버 핸드셰이크, 도구 검색, 장치 제어를 수행하지 않습니다.",
      ),
    },
    {
      name: c("LLM inference", "LLM 추론"),
      available: data.capabilities.llm_inference,
      detail: c(
        "No model requests or simulated model replies.",
        "모델에 요청하지 않으며 모델 응답을 모사하지 않습니다.",
      ),
    },
  ];
  return (
    <div className="page-stack lab-page">
      <PageHeader
        eyebrow={c("System", "시스템")}
        title={c("Settings", "설정")}
        description={c(
          "Read the local workspace configuration and its current API capabilities. These are facts, not permission switches.",
          "로컬 워크스페이스 구성과 현재 API 기능을 확인하세요. 이 항목은 상태 정보이며 권한 전환 스위치가 아닙니다.",
        )}
        actions={
          <div className="button-row">
            <Button onClick={() => navigate("ai-settings")}>
              {c("AI settings", "AI 설정")}
            </Button>
            <Button disabled={state === "loading"} onClick={reload}>
              <RefreshCw size={16} aria-hidden="true" />
              {state === "loading"
                ? c("Refreshing…", "새로 고침 중…")
                : c("Refresh workspace", "워크스페이스 새로 고침")}
            </Button>
          </div>
        }
      />
      {state === "error" && (
        <Notice tone="danger">
          {c(
            "Could not refresh the workspace. Check that the local API is running and retry. Displayed values are from the last loaded snapshot.",
            "워크스페이스를 새로 고치지 못했습니다. 로컬 API 실행 상태를 확인하고 다시 시도하세요. 표시된 값은 마지막으로 불러온 스냅샷입니다.",
          )}
        </Notice>
      )}
      {state === "success" && (
        <p role="status" className="muted">
          {c(
            "Workspace refreshed. No device connection was attempted.",
            "워크스페이스를 새로 고쳤습니다. 장치 연결은 시도하지 않았습니다.",
          )}
        </p>
      )}
      <Notice tone="warning">
        {c(
          "Local development only — not production authentication.",
          "로컬 개발 전용이며 운영 환경 인증을 제공하지 않습니다.",
        )}
      </Notice>
      <div className="grid-two">
        <Panel title={c("Application & API", "애플리케이션 및 API")}>
          <dl className="detail-list">
            <div>
              <dt>{c("Version", "버전")}</dt>
              <dd className="mono">{data.meta.version}</dd>
            </div>
            <div>
              <dt>{c("Operating mode", "운영 모드")}</dt>
              <dd>
                <Badge tone="warning">
                  {data.meta.mode} · {c("Offline", "오프라인")}
                </Badge>
              </dd>
            </div>
            <div>
              <dt>{c("Deployment", "배포 환경")}</dt>
              <dd>{c("Loopback development", "루프백 개발 환경")}</dd>
            </div>
            <div>
              <dt>{c("API base", "API 기본 경로")}</dt>
              <dd className="mono">/api/v1</dd>
            </div>
            <div>
              <dt>{c("Live execution", "실제 실행")}</dt>
              <dd>
                {data.meta.live_enabled
                  ? c("Enabled", "활성화")
                  : c("Disabled", "비활성화")}
              </dd>
            </div>
          </dl>
          <p className="muted">
            {c(
              "Same-origin API requests stay within the local app. API availability is shown separately in the top bar; OFFLINE describes execution mode.",
              "동일 출처 API 요청은 로컬 앱 범위에 머뭅니다. API 가용성은 상단 바에 별도로 표시되며 OFFLINE은 실행 모드를 뜻합니다.",
            )}
          </p>
        </Panel>
        <Panel title={c("Language & display", "언어 및 표시")}>
          <dl className="detail-list">
            <div>
              <dt>{c("Current language", "현재 언어")}</dt>
              <dd>{locale === "ko" ? "한국어" : "English"}</dd>
            </div>
          </dl>
          <p>
            {c(
              "Use the language selector in the top bar to switch between English and Korean.",
              "상단 바의 언어 선택기로 영어와 한국어를 전환하세요.",
            )}
          </p>
          <p className="muted">
            {c(
              "Operator-authored names and instructions are preserved as entered, not automatically translated.",
              "운영자가 작성한 이름과 지침은 입력한 그대로 유지되며 자동 번역되지 않습니다.",
            )}
          </p>
        </Panel>
      </div>
      <Panel
        title={c("Workspace capabilities", "워크스페이스 기능")}
        description={c(
          "Reported by the loaded workspace snapshot. Availability does not grant execution authority.",
          "불러온 워크스페이스 스냅샷의 기능 정보입니다. 기능 가용성이 실행 권한을 부여하지는 않습니다.",
        )}
      >
        <DataTable label={c("API capability matrix", "API 기능 표")}>
          <table className="table">
            <thead>
              <tr>
                <th>{c("Capability", "기능")}</th>
                <th>{c("Availability", "가용성")}</th>
                <th>{c("Scope", "범위")}</th>
              </tr>
            </thead>
            <tbody>
              {capabilities.map((item) => (
                <tr key={item.name}>
                  <th scope="row">{item.name}</th>
                  <td>
                    <Badge tone={item.available ? "info" : "neutral"}>
                      {item.available
                        ? c("Available", "사용 가능")
                        : c("Unavailable", "사용 불가")}
                    </Badge>
                  </td>
                  <td>{item.detail}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </DataTable>
      </Panel>
      <Panel
        title={c("Local draft storage", "로컬 초안 저장소")}
        actions={
          <Button onClick={() => navigate("audit")}>
            {c("View local audit log", "로컬 감사 로그 보기")}
            <ArrowRight size={16} aria-hidden="true" />
          </Button>
        }
      >
        <p>
          {c(
            "Drafts are stored in a JSON file managed by the local API, not in a production execution database. Do not store secrets.",
            "초안은 로컬 API가 관리하는 JSON 파일에 저장되며 운영 실행 데이터베이스가 아닙니다. 비밀 정보를 저장하지 마세요.",
          )}
        </p>
        <ul className="lab-checklist">
          <li>
            {c(
              "Up to 100 drafts per entity type; the audit log retains the 500 most recent events.",
              "항목 유형별 초안은 최대 100개이며 감사 로그는 최근 이벤트 500개를 보관합니다.",
            )}
          </li>
          <li>
            {c(
              "Single-process development storage; no multi-process durability or production access-control guarantee.",
              "단일 프로세스 개발용 저장소입니다. 다중 프로세스 내구성이나 운영 환경 접근 제어를 보장하지 않습니다.",
            )}
          </li>
          <li>
            {c(
              "Saving metadata never connects an MCP server, executes a Skill, or authorizes a test.",
              "메타데이터 저장은 MCP 서버 연결, Skill 실행, 시험 승인을 수행하지 않습니다.",
            )}
          </li>
        </ul>
      </Panel>
    </div>
  );
}
