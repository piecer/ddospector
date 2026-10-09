import { useState } from "react";
import type { FormEvent } from "react";
import { ArrowRight, Network, Plus, Unplug } from "lucide-react";
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
import { api } from "../../lib/api";
import type { McpServerInput, PageProps } from "../../lib/contracts";
import { choose } from "../../lib/i18n";
import { useDraft } from "./use-draft";
import { validEndpoint, validName } from "./validation";

const emptyDraft: McpServerInput = {
  name: "",
  endpoint: "",
  transport: "streamable_http",
  usage_instructions: "",
};

export function McpServersPage({ data, locale, navigate, refresh }: PageProps) {
  const c = (en: string, ko: string) => choose(locale, en, ko);
  const [open, setOpen] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const selected = data.mcp_servers.find((server) => server.id === selectedId);
  const [draft, setDraft] = useState<McpServerInput>(emptyDraft);
  const [invalid, setInvalid] = useState<
    "name" | "endpoint" | "instructions" | null
  >(null);
  const atLimit = data.mcp_servers.length >= 100;
  const mutation = useDraft(refresh, () => {
    setOpen(false);
    setDraft(emptyDraft);
    setInvalid(null);
  });
  const fieldsDisabled = mutation.busy || mutation.saved;
  const endpointLabel =
    draft.transport === "stdio"
      ? c("Registered server ID", "등록된 서버 ID")
      : c("HTTP(S) endpoint", "HTTP(S) 엔드포인트");
  const validationMessage =
    invalid === "name"
      ? c(
          "Name must contain 1–120 characters, without control characters.",
          "이름은 제어 문자 없이 1~120자로 입력하세요.",
        )
      : invalid === "instructions"
        ? c(
            "Usage instructions must contain 1–8,000 characters.",
            "사용 지침은 1~8,000자로 입력하세요.",
          )
        : draft.transport === "stdio"
          ? c(
              "Use 1–64 lowercase letters, digits, or hyphens; start with a letter.",
              "소문자로 시작하는 1~64자의 소문자, 숫자, 하이픈만 사용하세요.",
            )
          : c(
              "Enter an HTTP(S) URL up to 512 characters, without userinfo, spaces, query strings, or a fragment.",
              "사용자 정보, 공백, 쿼리 문자열, 프래그먼트가 없는 HTTP(S) URL을 최대 512자로 입력하세요.",
            );
  async function save(event: FormEvent) {
    event.preventDefault();
    if (mutation.busy) return;
    if (!mutation.saved) {
      const issue = !validName(draft.name)
        ? "name"
        : !validEndpoint(draft.endpoint, draft.transport)
          ? "endpoint"
          : !draft.usage_instructions.trim() ||
              draft.usage_instructions.length > 8000
            ? "instructions"
            : null;
      setInvalid(issue);
      if (issue || atLimit) return;
    }
    await mutation.submit(() =>
      api.createMcpServer({ ...draft, name: draft.name.trim() }),
    );
  }
  return (
    <div className="page-stack lab-page">
      <PageHeader
        eyebrow={c("Lab configuration", "실험실 구성")}
        title={c("MCP servers", "MCP 서버")}
        description={c(
          "Prepare server metadata and the instructions an AI agent should receive. Nothing connects automatically.",
          "서버 메타데이터와 AI 에이전트에 전달할 사용 지침을 준비합니다. 자동 연결은 수행하지 않습니다.",
        )}
        actions={
          <Button
            variant="primary"
            disabled={atLimit || mutation.busy}
            onClick={() => setOpen(true)}
          >
            <Plus size={16} aria-hidden="true" />
            {c("Add MCP server", "MCP 서버 추가")}
          </Button>
        }
      />
      {atLimit && (
        <Notice tone="warning">
          {c(
            "MCP server limit reached (100 drafts).",
            "MCP 서버 한도에 도달했습니다(초안 100개).",
          )}
        </Notice>
      )}
      <Notice tone="warning">
        {c(
          "Saved endpoints are draft data only. No handshake, tool discovery, command execution, or endpoint request is performed.",
          "저장된 엔드포인트는 초안 데이터일 뿐입니다. 핸드셰이크, 도구 검색, 명령 실행, 엔드포인트 요청은 수행하지 않습니다.",
        )}
      </Notice>
      <Panel
        title={c("Server registry drafts", "서버 등록 초안")}
        actions={
          <Badge>
            {data.mcp_servers.length} {c("drafts", "개 초안")}
          </Badge>
        }
      >
        {data.mcp_servers.length === 0 ? (
          <EmptyState
            icon={<Network size={28} />}
            title={c(
              "No MCP server drafts yet",
              "등록된 MCP 서버 초안이 없습니다",
            )}
            description={c(
              "Save a server reference and usage guidance, then assign it to an agent profile.",
              "서버 참조와 사용 지침을 저장한 뒤 에이전트 프로파일에 할당하세요.",
            )}
          />
        ) : (
          <DataTable label={c("MCP server drafts", "MCP 서버 초안")}>
            <table className="table">
              <thead>
                <tr>
                  <th>{c("Server", "서버")}</th>
                  <th>{c("Endpoint", "엔드포인트")}</th>
                  <th>{c("Transport", "전송 방식")}</th>
                  <th>{c("Status", "상태")}</th>
                  <th>{c("Instructions", "사용 지침")}</th>
                </tr>
              </thead>
              <tbody>
                {data.mcp_servers.map((server) => (
                  <tr key={server.id}>
                    <td>{server.name}</td>
                    <td className="mono">{server.endpoint}</td>
                    <td>
                      {server.transport === "stdio"
                        ? c("Standard I/O", "표준 입출력")
                        : c("Streamable HTTP", "스트리밍 HTTP")}
                    </td>
                    <td>
                      <Badge tone="warning">
                        {c("Draft · not connected", "초안 · 연결 안 됨")}
                      </Badge>
                    </td>
                    <td>
                      <Button
                        variant="ghost"
                        aria-label={
                          c("View instructions: ", "사용 지침 보기: ") +
                          server.name
                        }
                        onClick={() => setSelectedId(server.id)}
                      >
                        {c("View instructions", "사용 지침 보기")}
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </DataTable>
        )}
      </Panel>
      <div className="grid-two">
        <Panel title={c("Connection boundary", "연결 제한")}>
          <p id="mcp-connect-reason" className="muted">
            {c(
              "MCP connections are unavailable in this local draft workspace.",
              "이 로컬 초안 워크스페이스에서는 MCP 연결을 사용할 수 없습니다.",
            )}
          </p>
          <Button disabled aria-describedby="mcp-connect-reason">
            <Unplug size={16} aria-hidden="true" />
            {c("Connect", "연결")}
          </Button>
        </Panel>
        <Panel
          title={c(
            "Give the agent useful context",
            "에이전트에 필요한 맥락 제공",
          )}
        >
          <p className="muted">
            {c(
              "Describe intended use, prerequisites, permitted scope, and required evidence. Assign saved drafts in the Agent workspace.",
              "사용 목적, 사전 조건, 허용 범위, 필요한 증거를 작성하세요. 저장한 초안은 AI 에이전트 화면에서 할당할 수 있습니다.",
            )}
          </p>
          <Button onClick={() => navigate("agent")}>
            {c("Open Agent workspace", "AI 에이전트 열기")}
            <ArrowRight size={16} aria-hidden="true" />
          </Button>
        </Panel>
      </div>
      <Dialog
        open={open}
        recoveryOnly={mutation.saved}
        title={c("Add MCP server draft", "MCP 서버 초안 추가")}
        onClose={() => setOpen(false)}
      >
        <form
          className="form-stack"
          onSubmit={save}
          noValidate
          aria-busy={mutation.busy}
        >
          <p className="muted">
            {c(
              "All fields are required. Never store credentials, access tokens, or other secrets in a draft.",
              "모든 항목은 필수입니다. 초안에 인증 정보, 액세스 토큰, 기타 비밀 정보를 저장하지 마세요.",
            )}
          </p>
          {invalid && (
            <Notice tone="danger">
              <span id="mcp-validation">{validationMessage}</span>
            </Notice>
          )}
          {mutation.error && (
            <Notice tone="danger">
              {mutation.error === "save"
                ? c(
                    "Could not save the draft. Check the local API and retry; your inputs are preserved.",
                    "초안을 저장하지 못했습니다. 로컬 API를 확인하고 다시 시도하세요. 입력 내용은 유지됩니다.",
                  )
                : c(
                    "Draft saved, but the workspace could not refresh. Retry refresh without creating another draft.",
                    "초안은 저장되었지만 워크스페이스를 새로 고치지 못했습니다. 초안을 다시 만들지 않고 새로 고침만 재시도하세요.",
                  )}
            </Notice>
          )}
          <Field label={c("Name", "이름")}>
            <input
              required
              maxLength={120}
              disabled={fieldsDisabled}
              aria-invalid={invalid === "name"}
              aria-describedby={
                invalid === "name" ? "mcp-validation" : undefined
              }
              value={draft.name}
              onChange={(event) =>
                setDraft({ ...draft, name: event.target.value })
              }
            />
          </Field>
          <Field label={c("Transport", "전송 방식")}>
            <select
              disabled={fieldsDisabled}
              value={draft.transport}
              onChange={(event) => {
                setDraft({
                  ...draft,
                  transport: event.target.value as McpServerInput["transport"],
                  endpoint: "",
                });
                setInvalid(null);
              }}
            >
              <option value="streamable_http">
                {c("Streamable HTTP", "스트리밍 HTTP")}
              </option>
              <option value="stdio">
                {c("Standard I/O (registry ID)", "표준 입출력(등록 ID)")}
              </option>
            </select>
          </Field>
          <Field label={endpointLabel}>
            <input
              required
              maxLength={draft.transport === "stdio" ? 64 : 512}
              disabled={fieldsDisabled}
              spellCheck={false}
              autoCapitalize="none"
              aria-invalid={invalid === "endpoint"}
              aria-describedby={
                invalid === "endpoint"
                  ? "mcp-endpoint-hint mcp-validation"
                  : "mcp-endpoint-hint"
              }
              value={draft.endpoint}
              onChange={(event) =>
                setDraft({ ...draft, endpoint: event.target.value })
              }
            />
          </Field>
          <p className="muted" id="mcp-endpoint-hint">
            {draft.transport === "stdio"
              ? c(
                  "Use a registered identifier, not an executable path or shell command.",
                  "실행 파일 경로나 셸 명령이 아닌 등록된 식별자를 사용하세요.",
                )
              : c(
                  "HTTP or HTTPS only, up to 512 characters. No userinfo or fragment. Saving does not contact this URL.",
                  "HTTP 또는 HTTPS만 허용하며 최대 512자입니다. 사용자 정보와 프래그먼트는 제외하세요. 저장 시 이 URL에 접속하지 않습니다.",
                )}
          </p>
          <Field label={c("AI usage instructions", "AI 사용 지침")}>
            <textarea
              rows={6}
              required
              maxLength={8000}
              disabled={fieldsDisabled}
              aria-invalid={invalid === "instructions"}
              aria-describedby={
                invalid === "instructions"
                  ? "mcp-instructions-hint mcp-validation"
                  : "mcp-instructions-hint"
              }
              value={draft.usage_instructions}
              onChange={(event) =>
                setDraft({ ...draft, usage_instructions: event.target.value })
              }
            />
          </Field>
          <p className="muted" id="mcp-instructions-hint">
            {c(
              "Up to 8,000 characters. Explain when to use this server, prerequisites, restrictions, and evidence to collect.",
              "최대 8,000자입니다. 서버 사용 시점, 사전 조건, 제한 사항, 수집할 증거를 설명하세요.",
            )}
          </p>
          <Notice>
            {c(
              "Instructions are context, not execution authority.",
              "사용 지침은 맥락 정보이며 실행 권한이 아닙니다.",
            )}
          </Notice>
          <div className="button-row">
            <Button onClick={() => setOpen(false)}>{c("Close", "닫기")}</Button>
            <Button
              type="submit"
              variant="primary"
              disabled={mutation.busy || (atLimit && !mutation.saved)}
            >
              {mutation.busy
                ? c("Saving…", "저장 중…")
                : mutation.saved
                  ? c("Retry refresh", "새로 고침 재시도")
                  : c("Save draft", "초안 저장")}
            </Button>
          </div>
        </form>
      </Dialog>
      <Dialog
        open={Boolean(selected)}
        title={selected?.name ?? c("MCP server details", "MCP 서버 상세")}
        onClose={() => setSelectedId(null)}
      >
        {selected && (
          <div className="form-stack">
            <Badge tone="warning">
              {c("Draft · not connected", "초안 · 연결 안 됨")}
            </Badge>
            <dl className="detail-list">
              <div>
                <dt>{c("Endpoint", "엔드포인트")}</dt>
                <dd className="mono">{selected.endpoint}</dd>
              </div>
              <div>
                <dt>{c("Discovered tools", "검색된 도구")}</dt>
                <dd>
                  {selected.tools_count} ·{" "}
                  {c("Discovery has not run", "도구 검색 미수행")}
                </dd>
              </div>
            </dl>
            <h3>{c("AI usage instructions", "AI 사용 지침")}</h3>
            <p className="lab-instructions">{selected.usage_instructions}</p>
            <Notice>
              {c(
                "Instructions are context, not execution authority.",
                "사용 지침은 맥락 정보이며 실행 권한이 아닙니다.",
              )}
            </Notice>
            <Button
              onClick={() => {
                setSelectedId(null);
                navigate("agent");
              }}
            >
              {c("Assign in Agent workspace", "AI 에이전트에서 할당")}
            </Button>
          </div>
        )}
      </Dialog>
    </div>
  );
}
