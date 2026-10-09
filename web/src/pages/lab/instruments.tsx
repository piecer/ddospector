import { ArrowRight, RadioTower } from "lucide-react";
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

export function InstrumentsPage({ data, locale, navigate }: PageProps) {
  const c = (en: string, ko: string) => choose(locale, en, ko);
  return (
    <div className="page-stack lab-page">
      <PageHeader
        eyebrow={c("Lab configuration", "실험실 구성")}
        title={c("Instruments", "계측기")}
        description={c(
          "Prepare the integration path for future lab equipment. This workspace does not discover or operate hardware.",
          "향후 실험 장비 연동 경로를 준비합니다. 이 워크스페이스에서는 하드웨어를 검색하거나 작동하지 않습니다.",
        )}
        actions={
          <Button disabled aria-describedby="instrument-discovery-reason">
            {c("Discover instruments", "계측기 검색")}
          </Button>
        }
      />
      <Notice tone="warning">
        <span id="instrument-discovery-reason">
          {c(
            "Instrument discovery and hardware control are not implemented.",
            "계측기 검색과 하드웨어 제어는 구현되지 않았습니다.",
          )}
        </span>
      </Notice>
      <Panel
        title={c("Instrument inventory", "계측기 목록")}
        actions={
          <Badge>
            {data.instruments.length} {c("records", "개 기록")}
          </Badge>
        }
      >
        {data.instruments.length === 0 ? (
          <EmptyState
            icon={<RadioTower size={30} />}
            title={c("No instruments configured", "구성된 계측기가 없습니다")}
            description={c(
              "There are no registered instruments. An MCP server draft is a planning step, not a connected device.",
              "등록된 계측기가 없습니다. MCP 서버 초안은 계획 단계이며 연결된 장치가 아닙니다.",
            )}
            action={
              <Button variant="primary" onClick={() => navigate("mcp-servers")}>
                {c("Prepare an MCP server draft", "MCP 서버 초안 준비")}
                <ArrowRight size={16} aria-hidden="true" />
              </Button>
            }
          />
        ) : (
          <DataTable label={c("Instrument records", "계측기 기록")}>
            <table className="table">
              <thead>
                <tr>
                  <th>{c("Name", "이름")}</th>
                  <th>{c("Recorded role", "기록된 역할")}</th>
                  <th>{c("Recorded status", "기록된 상태")}</th>
                </tr>
              </thead>
              <tbody>
                {data.instruments.map((instrument) => (
                  <tr key={instrument.id}>
                    <td>{instrument.name}</td>
                    <td>{instrument.role}</td>
                    <td>{instrument.status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </DataTable>
        )}
        <p className="muted">
          {c(
            "Inventory records are not live connection evidence.",
            "목록 기록은 실제 연결의 증거가 아닙니다.",
          )}
        </p>
      </Panel>
      <div className="grid-three">
        <Panel title={c("01 · Define the role", "01 · 역할 정의")}>
          <p className="muted">
            {c(
              "Document the intended measurement role, interfaces, and constraints before preparing a binding.",
              "연결 설정을 준비하기 전에 계측 역할, 인터페이스, 제약 조건을 정리하세요.",
            )}
          </p>
        </Panel>
        <Panel title={c("02 · Write usage guidance", "02 · 사용 지침 작성")}>
          <p className="muted">
            {c(
              "Prepare an MCP server draft with prerequisites and evidence requirements for the agent.",
              "에이전트에 필요한 사전 조건과 증거 요건을 포함한 MCP 서버 초안을 준비하세요.",
            )}
          </p>
        </Panel>
        <Panel title={c("03 · Await integration", "03 · 연동 구현 대기")}>
          <p className="muted">
            {c(
              "A future adapter, verified capabilities, and a Safety Gate are required before any device operation.",
              "장치를 작동하려면 향후 어댑터 구현, 기능 검증, 안전 게이트가 필요합니다.",
            )}
          </p>
        </Panel>
      </div>
    </div>
  );
}
