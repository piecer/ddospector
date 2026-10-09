import type { PageProps } from "../lib/contracts";
import type { RouteId } from "../lib/navigation";
import {
  ArrowDownToLine,
  ArrowRight,
  BookOpen,
  Bot,
  Check,
  ChevronRight,
  CircleDashed,
  Crosshair,
  Layers3,
  LockKeyhole,
  Network,
  Plus,
  Radar,
  RadioTower,
  Server,
  Shield,
  Sparkles,
  TerminalSquare,
} from "lucide-react";
import { choose, formatDate, text } from "../lib/i18n";
import { Badge, Button, EmptyState, PageHeader, Panel } from "../components/ui";

export function OverviewPage({ data, locale, navigate }: PageProps) {
  const c = (en: string, ko: string) => choose(locale, en, ko);
  const steps: Array<{
    title: string;
    description: string;
    route: RouteId;
    done: boolean;
  }> = [
    {
      title: c("Define your test target", "시험 대상 정의"),
      description: c(
        "Register a DUT or service endpoint.",
        "DUT 또는 시험 서비스 주소를 등록하세요.",
      ),
      route: "targets",
      done: data.targets.length > 0,
    },
    {
      title: c("Describe the MCP connection", "MCP 연결 정보 구성"),
      description: c(
        "Add a server and its usage guidance.",
        "서버와 도구 사용 지침을 추가하세요.",
      ),
      route: "mcp-servers",
      done: data.mcp_servers.length > 0,
    },
    {
      title: c("Give the agent its Skills", "에이전트에 Skill 부여"),
      description: c(
        "Assign procedures, not unrestricted authority.",
        "작업 절차를 부여하고 권한은 분리하세요.",
      ),
      route: "agent",
      done: data.agent_profile.skill_ids.length > 0,
    },
    {
      title: c("Prepare a campaign draft", "캠페인 초안 준비"),
      description: c(
        "Connect a target with a test profile.",
        "대상과 시험 프로파일을 연결하세요.",
      ),
      route: "campaigns",
      done: data.campaigns.length > 0,
    },
  ];
  const configured = steps.filter((step) => step.done).length;
  const recentEvents = [...data.audit]
    .sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at))
    .slice(0, 4);
  const metrics = [
    {
      label: c("Target drafts", "시험 대상 초안"),
      value: data.targets.length,
      description: c(
        "Not yet approved for testing",
        "시험 실행 승인은 아직 없음",
      ),
      icon: Crosshair,
      testId: "target-count",
    },
    {
      label: c("MCP server drafts", "MCP 서버 초안"),
      value: data.mcp_servers.length,
      description: c(
        "No connections have been verified",
        "연결이 검증된 서버는 없음",
      ),
      icon: Network,
    },
    {
      label: c("Assigned Skills", "부여된 Skill"),
      value: data.agent_profile.skill_ids.length,
      description: c(
        "Guidance for the review-only agent",
        "검토 전용 에이전트의 작업 지침",
      ),
      icon: BookOpen,
    },
    {
      label: c("Campaign drafts", "캠페인 초안"),
      value: data.campaigns.length,
      description: c("No live executions", "LIVE 실행 없음"),
      icon: Layers3,
    },
  ];
  const flow = [
    {
      label: c("Traffic source", "트래픽 발생기"),
      name: "tcpreplay",
      icon: TerminalSquare,
      route: "profiles" as RouteId,
    },
    {
      label: c("Ingress capture", "앞단 관측"),
      name: "tcpdump",
      icon: Radar,
      route: "instruments" as RouteId,
    },
    {
      label: c("Device under test", "검증 대상 장비"),
      name: "DUT",
      icon: Shield,
      route: "targets" as RouteId,
    },
    {
      label: c("Egress observation", "뒷단 관측"),
      name: c("MCP instrument", "MCP 계측기"),
      icon: RadioTower,
      route: "instruments" as RouteId,
    },
    {
      label: c("Protected service", "보호 대상 서비스"),
      name: c("Test sink", "시험 수신 서버"),
      icon: Server,
      route: "targets" as RouteId,
    },
  ];
  return (
    <div className="page-stack overview-page">
      <PageHeader
        eyebrow={c("CONTROL CENTER", "CONTROL CENTER")}
        title={c("Validation workspace", "검증 워크스페이스")}
        description={c(
          "Configure the lab. Give the agent its procedures. Keep every conclusion tied to evidence.",
          "실험 환경과 에이전트의 작업 지침을 구성하고, 모든 판정을 증거와 연결합니다.",
        )}
        actions={
          <Button variant="primary" onClick={() => navigate("targets")}>
            <Plus size={16} aria-hidden="true" />
            {c("Add test target", "시험 대상 추가")}
          </Button>
        }
      />
      <div className="readiness-banner">
        <div className="readiness-symbol">
          <LockKeyhole size={18} aria-hidden="true" />
        </div>
        <div>
          <strong>
            {c(
              "Configuration is open. LIVE execution stays locked.",
              "환경 구성은 열려 있고, LIVE 실행은 잠겨 있습니다.",
            )}
          </strong>
          <p>
            {c(
              "This build saves local drafts and previews agent instructions. It does not connect equipment or generate traffic.",
              "현재 버전은 로컬 초안 저장과 에이전트 지침 미리보기를 제공합니다. 장비 연결이나 트래픽 송신은 하지 않습니다.",
            )}
          </p>
        </div>
        <Badge tone="warning">{c("SETUP MODE", "구성 모드")}</Badge>
      </div>
      <div className="metric-grid">
        {metrics.map((metric) => (
          <section className="metric-card" key={metric.label}>
            <div className="metric-top">
              <span>{metric.label}</span>
              <metric.icon size={17} aria-hidden="true" />
            </div>
            <strong className="metric-value" data-testid={metric.testId}>
              {metric.value}
            </strong>
            <div className="metric-description">{metric.description}</div>
          </section>
        ))}
      </div>
      <Panel
        title={c(
          "A clear boundary between control and traffic",
          "제어와 시험 트래픽을 분리한 구조",
        )}
        description={c(
          "Planned data path · not live telemetry",
          "구성도 · 실시간 계측 아님",
        )}
        className="topology-panel"
        actions={
          <Badge>
            <CircleDashed size={12} aria-hidden="true" />
            {c("Not connected", "미연결")}
          </Badge>
        }
      >
        <div className="topology-control">
          <span>
            <Bot size={16} aria-hidden="true" />
            {c("AI agent + Skills", "AI 에이전트 + Skills")}
          </span>
          <ArrowRight size={15} aria-hidden="true" />
          <span>
            <Shield size={15} aria-hidden="true" />
            {c("Approval & safety gate", "승인 · 안전 검증")}
          </span>
          <ArrowRight size={15} aria-hidden="true" />
          <span>
            <Network size={15} aria-hidden="true" />
            MCP Broker
          </span>
        </div>
        <div
          className="topology-rail"
          role="region"
          aria-label={c(
            "Planned isolated lab topology",
            "계획된 격리 실험망 구성도",
          )}
          tabIndex={0}
        >
          {flow.map((node, index) => (
            <div
              className={"topology-step " + (index === 2 ? "topology-dut" : "")}
              key={node.name}
            >
              <span className="topology-index">
                {String(index + 1).padStart(2, "0")}
              </span>
              <button
                className="topology-node"
                onClick={() => navigate(node.route)}
                aria-label={node.label}
              >
                <node.icon size={25} strokeWidth={1.5} />
              </button>
              <strong>{node.name}</strong>
              <span>{node.label}</span>
              {index < flow.length - 1 && (
                <div className="topology-edge" aria-hidden="true">
                  <ArrowRight size={14} />
                </div>
              )}
            </div>
          ))}
        </div>
        <div className="topology-caption">
          <LockKeyhole size={13} aria-hidden="true" />
          <span>{c("Isolated data plane", "격리된 데이터 평면")}</span>
          <span className="topology-caption-divider" />
          <span>
            {c(
              "One LIVE run at a time, once the runtime is verified",
              "실행 엔진 검증 후에도 동시 LIVE는 1개",
            )}
          </span>
        </div>
      </Panel>
      <div className="overview-lower-grid">
        <Panel
          title={c("Build your workspace", "워크스페이스 준비")}
          description={c(
            "Configuration progress — not live readiness.",
            "구성 진행 상태이며 LIVE 준비 완료를 뜻하지 않습니다.",
          )}
          actions={
            <span className="setup-count mono">
              {configured} / {steps.length}
            </span>
          }
        >
          <div className="setup-list">
            {steps.map((step, index) => (
              <button
                className="setup-step"
                key={step.route}
                onClick={() => navigate(step.route)}
              >
                <span
                  className={
                    "setup-step-number " + (step.done ? "setup-step-done" : "")
                  }
                >
                  {step.done ? (
                    <Check size={15} />
                  ) : (
                    String(index + 1).padStart(2, "0")
                  )}
                </span>
                <span className="setup-step-text">
                  <strong>{step.title}</strong>
                  <small>{step.description}</small>
                </span>
                <ChevronRight size={17} aria-hidden="true" />
              </button>
            ))}
          </div>
        </Panel>
        <Panel
          title={c(
            "An agent with clear instructions",
            "지침이 분명한 AI 에이전트",
          )}
          actions={<Badge tone="info">REVIEW_ONLY</Badge>}
          className="agent-overview"
        >
          <div className="agent-overview-mark">
            <Sparkles size={23} aria-hidden="true" />
          </div>
          <h3>
            {c(
              "Skills define how. Policies decide if.",
              "Skill은 절차를, 정책은 허용 여부를.",
            )}
          </h3>
          <p className="muted">
            {c(
              "Assign reusable Skills and MCP usage guidance. Inspect the assembled context before a model or tool is ever involved.",
              "재사용할 Skill과 MCP 사용 지침을 부여하세요. 모델이나 도구를 실행하기 전에 구성된 컨텍스트를 확인할 수 있습니다.",
            )}
          </p>
          <div className="overview-skill-list">
            {data.skills.slice(0, 3).map((skill) => (
              <div key={skill.id}>
                <BookOpen size={14} aria-hidden="true" />
                <span>{text(skill.name, locale)}</span>
                <span className="mono">v{skill.version}</span>
              </div>
            ))}
            {data.skills.length === 0 && (
              <span className="muted">
                {c("Skill catalog not loaded", "Skill 목록이 비어 있습니다")}
              </span>
            )}
          </div>
          <Button onClick={() => navigate("agent")}>
            {c("Open agent workspace", "에이전트 구성 열기")}
            <ArrowRight size={15} aria-hidden="true" />
          </Button>
        </Panel>
      </div>
      <Panel
        title={c("Recent workspace activity", "최근 워크스페이스 활동")}
        description={c(
          "Actual draft changes only. Test results appear after verified execution.",
          "실제로 저장한 초안 변경만 표시합니다. 시험 결과는 실행 검증 이후 제공됩니다.",
        )}
        actions={
          <Button variant="ghost" onClick={() => navigate("audit")}>
            {c("View audit log", "감사 로그 보기")}
            <ArrowRight size={14} aria-hidden="true" />
          </Button>
        }
      >
        {data.audit.length === 0 ? (
          <EmptyState
            icon={<ArrowDownToLine size={21} />}
            title={c("A clean start", "새로운 시작")}
            description={c(
              "Register a target or add a Skill. Your changes will be recorded here.",
              "시험 대상을 등록하거나 Skill을 추가하면 변경 기록이 여기에 표시됩니다.",
            )}
          />
        ) : (
          <div className="activity-list">
            {recentEvents.map((event) => (
              <div className="activity-item" key={event.id}>
                <span className="activity-dot" />
                <div>
                  <strong>{event.action}</strong>
                  <small className="mono">{event.entity_id}</small>
                </div>
                <time dateTime={event.created_at}>
                  {formatDate(event.created_at, locale)}
                </time>
              </div>
            ))}
          </div>
        )}
      </Panel>
    </div>
  );
}
