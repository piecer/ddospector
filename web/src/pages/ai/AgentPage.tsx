import { useState } from "react";
import type { FormEvent } from "react";
import type { AgentProfileInput, PageProps } from "../../lib/contracts";
import { api } from "../../lib/api";
import { choose, text } from "../../lib/i18n";
import {
  Badge,
  Button,
  EmptyState,
  Field,
  Notice,
  PageHeader,
  Panel,
} from "../../components/ui";
import { ContextPreviewPanel } from "./ContextPreviewPanel";
import { SkillDetails } from "./SkillDetails";

function profileInput(profile: AgentProfileInput): AgentProfileInput {
  return {
    name: profile.name,
    skill_ids: [...profile.skill_ids],
    mcp_server_ids: [...profile.mcp_server_ids],
  };
}

export function AgentPage({ data, locale, refresh, navigate }: PageProps) {
  const t = (en: string, ko: string) => choose(locale, en, ko);
  const [draft, setDraft] = useState(() => profileInput(data.agent_profile));
  const [baseline, setBaseline] = useState(() =>
    profileInput(data.agent_profile),
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const [refreshFailed, setRefreshFailed] = useState(false);
  const incomingKey = JSON.stringify(profileInput(data.agent_profile));
  const [sourceKey, setSourceKey] = useState(incomingKey);
  const [conflict, setConflict] = useState(false);
  const dirty = JSON.stringify(draft) !== JSON.stringify(baseline);
  // Reconcile a new snapshot before rendering, without rebasing local edits.
  if (sourceKey !== incomingKey) {
    setSourceKey(incomingKey);
    if (JSON.stringify(baseline) !== incomingKey) setSaved(false);
    if (!dirty || JSON.stringify(draft) === incomingKey) {
      setDraft(profileInput(data.agent_profile));
      setBaseline(profileInput(data.agent_profile));
      setConflict(false);
    } else {
      setConflict(JSON.stringify(baseline) !== incomingKey);
    }
  }
  const missingSkills = draft.skill_ids.filter(
    (id) => !data.skills.some((skill) => skill.id === id),
  );
  const missingServers = draft.mcp_server_ids.filter(
    (id) => !data.mcp_servers.some((server) => server.id === id),
  );
  const missing = missingSkills.length > 0 || missingServers.length > 0;
  function update(value: AgentProfileInput) {
    setDraft(value);
    setSaved(false);
    setError("");
  }
  function toggle(key: "skill_ids" | "mcp_server_ids", id: string) {
    update({
      ...draft,
      [key]: draft[key].includes(id)
        ? draft[key].filter((value) => value !== id)
        : [...draft[key], id],
    });
  }
  async function reload() {
    try {
      await refresh();
      setRefreshFailed(false);
    } catch {
      setRefreshFailed(true);
    }
  }
  async function save(event: FormEvent) {
    event.preventDefault();
    if (busy || !dirty || missing || conflict) return;
    if (!draft.name.trim() || draft.name.length > 120) {
      setError(
        t(
          "Enter an agent name of 1–120 characters, not only whitespace.",
          "공백만 있는 이름은 사용할 수 없습니다. 에이전트 이름을 1~120자로 입력하세요.",
        ),
      );
      return;
    }
    setBusy(true);
    setError("");
    setSaved(false);
    try {
      const result = profileInput(await api.saveAgentProfile(draft));
      setDraft(result);
      setBaseline(result);
      setSaved(true);
      setConflict(false);
      await reload();
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : t("Unable to save the assignment.", "할당을 저장할 수 없습니다."),
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="page-stack ai-page">
      <PageHeader
        eyebrow={t("AI & governance", "AI 및 거버넌스")}
        title={t("Agent", "에이전트")}
        description={t(
          "Compose a review-only agent from Skills and registered MCP usage instructions.",
          "스킬과 등록된 MCP 사용 지침을 조합하여 검토 전용 에이전트를 구성하세요.",
        )}
        actions={<Badge tone="info">REVIEW_ONLY</Badge>}
      />
      <Notice tone="warning">
        {t(
          "Skills are guidance, not approval authority. MCP bindings and the Safety Gate remain authoritative. Saving an assignment is not operational approval.",
          "스킬은 지침이며 승인 권한이 아닙니다. MCP 바인딩과 Safety Gate의 권한을 대체하지 않습니다. 할당 저장은 운영 승인이 아닙니다.",
        )}
      </Notice>
      <form
        className="form-stack"
        onSubmit={save}
        aria-label={t("Agent assignment", "에이전트 할당")}
      >
        {conflict && (
          <Notice tone="warning">
            <p>
              {t(
                "The saved profile changed while you were editing. Your unsaved draft is preserved; resolve the conflict before saving or previewing.",
                "편집 중 저장된 프로필이 변경되었습니다. 저장하지 않은 초안은 유지됩니다. 저장하거나 미리보기 전에 충돌을 해결하세요.",
              )}
            </p>
            <Button
              disabled={busy}
              onClick={() => {
                const current = profileInput(data.agent_profile);
                update(current);
                setBaseline(current);
                setConflict(false);
              }}
            >
              {t(
                "Use refreshed profile (discard my edits)",
                "새로고침된 프로필 사용 (내 수정 취소)",
              )}
            </Button>
          </Notice>
        )}
        <Panel
          title={t("Agent profile", "에이전트 프로필")}
          actions={
            <Badge tone={dirty ? "warning" : "neutral"}>
              {dirty
                ? t("Unsaved changes", "저장하지 않은 변경 사항")
                : t("Saved configuration", "저장된 설정")}
            </Badge>
          }
        >
          <Field label={t("Agent name", "에이전트 이름")}>
            <input
              required
              maxLength={120}
              disabled={busy}
              value={draft.name}
              onChange={(event) =>
                update({ ...draft, name: event.target.value })
              }
            />
          </Field>
          <p className="muted">
            {t(
              "Local draft configuration only. Instructions never enable execution.",
              "로컬 초안 설정 전용입니다. 지침이 실행을 활성화하지 않습니다.",
            )}
          </p>
        </Panel>
        {missing && (
          <Notice tone="warning">
            <p>
              {t(
                "Some assigned references are unavailable. Remove them explicitly or refresh the workspace before saving or previewing.",
                "일부 할당 항목을 사용할 수 없습니다. 저장하거나 미리보기 전에 해당 항목을 직접 제거하거나 워크스페이스를 새로고침하세요.",
              )}
            </p>
            <ul>
              {missingSkills.map((id) => (
                <li key={id}>
                  <code>{id}</code>{" "}
                  <Button
                    disabled={busy}
                    aria-label={t(
                      `Remove unavailable Skill: ${id}`,
                      `사용할 수 없는 스킬 제거: ${id}`,
                    )}
                    onClick={() => toggle("skill_ids", id)}
                  >
                    {t("Remove Skill", "스킬 제거")}
                  </Button>
                </li>
              ))}
              {missingServers.map((id) => (
                <li key={id}>
                  <code>{id}</code>{" "}
                  <Button
                    disabled={busy}
                    aria-label={t(
                      `Remove unavailable MCP server: ${id}`,
                      `사용할 수 없는 MCP 서버 제거: ${id}`,
                    )}
                    onClick={() => toggle("mcp_server_ids", id)}
                  >
                    {t("Remove server", "서버 제거")}
                  </Button>
                </li>
              ))}
            </ul>
          </Notice>
        )}
        <fieldset disabled={busy} className="ai-fieldset grid-two">
          <Panel
            title={t("Assigned Skills", "할당할 스킬")}
            description={t(
              "Select the instruction sets this agent should use.",
              "에이전트가 사용할 지침 모음을 선택하세요.",
            )}
            actions={
              <Button variant="ghost" onClick={() => navigate("skills")}>
                {t("Skill library", "스킬 라이브러리")}
              </Button>
            }
          >
            {!data.skills.length && (
              <EmptyState
                title={t(
                  "No Skills available",
                  "사용할 수 있는 스킬이 없습니다",
                )}
                description={t(
                  "The workspace returned no Skills. Open the library to create a draft.",
                  "워크스페이스에서 반환된 스킬이 없습니다. 라이브러리에서 초안을 만드세요.",
                )}
              />
            )}
            <ul className="ai-choice-list">
              {data.skills.map((skill) => (
                <li className="ai-choice" key={skill.id}>
                  <label>
                    <input
                      type="checkbox"
                      aria-label={t(
                        `Assign ${text(skill.name, locale)}`,
                        `${text(skill.name, locale)} 할당`,
                      )}
                      checked={draft.skill_ids.includes(skill.id)}
                      onChange={() => toggle("skill_ids", skill.id)}
                    />
                    <span>
                      <strong>{text(skill.name, locale)}</strong>
                      <span className="muted">
                        {text(skill.description, locale)}
                      </span>
                    </span>
                    <Badge>{skill.version}</Badge>
                  </label>
                  <details>
                    <summary>{t("Read instructions", "지침 읽기")}</summary>
                    <SkillDetails skill={skill} locale={locale} />
                  </details>
                </li>
              ))}
            </ul>
          </Panel>
          <Panel
            title={t("MCP usage instructions", "MCP 사용 지침")}
            description={t(
              "Assignments reference registered metadata, not a verified connection or tool capability.",
              "할당은 등록된 메타데이터를 참조하며, 연결이나 도구 기능이 검증되었다는 뜻이 아닙니다.",
            )}
            actions={
              <Button variant="ghost" onClick={() => navigate("mcp-servers")}>
                {t("Manage servers", "서버 관리")}
              </Button>
            }
          >
            {!data.mcp_servers.length && (
              <EmptyState
                title={t(
                  "No registered MCP servers",
                  "등록된 MCP 서버가 없습니다",
                )}
                description={t(
                  "Register an MCP draft with usage instructions first. Registration will not connect to a server.",
                  "사용 지침이 포함된 MCP 초안을 먼저 등록하세요. 등록해도 서버에 연결하지 않습니다.",
                )}
              />
            )}
            <ul className="ai-choice-list">
              {data.mcp_servers.map((server) => (
                <li className="ai-choice" key={server.id}>
                  <label>
                    <input
                      type="checkbox"
                      aria-label={t(
                        `Assign ${server.name}`,
                        `${server.name} 할당`,
                      )}
                      checked={draft.mcp_server_ids.includes(server.id)}
                      onChange={() => toggle("mcp_server_ids", server.id)}
                    />
                    <strong>{server.name}</strong>
                  </label>
                  <div className="chips">
                    <Badge tone="warning">
                      {t(
                        "Registered draft · not connected",
                        "등록된 초안 · 연결 안 됨",
                      )}
                    </Badge>
                    <code>{server.transport}</code>
                  </div>
                  <p className="mono muted">{server.endpoint}</p>
                  <p className="ai-usage">{server.usage_instructions}</p>
                </li>
              ))}
            </ul>
          </Panel>
        </fieldset>
        <div className="ai-save-row">
          <p className="muted">
            {t(
              `${draft.skill_ids.length} Skills · ${draft.mcp_server_ids.length} MCP servers selected`,
              `스킬 ${draft.skill_ids.length}개 · MCP 서버 ${draft.mcp_server_ids.length}개 선택됨`,
            )}
          </p>
          <Button
            type="submit"
            variant="primary"
            disabled={busy || !dirty || missing || conflict}
          >
            {busy
              ? t("Saving assignment…", "할당 저장 중…")
              : t("Save assignment", "할당 저장")}
          </Button>
        </div>
        {error && (
          <Notice tone="danger">
            <strong>
              {t(
                "Assignment not saved. Your edits are preserved.",
                "할당을 저장하지 못했습니다. 수정 내용은 유지됩니다.",
              )}
            </strong>
            <p>{error}</p>
          </Notice>
        )}
        {saved && (
          <div role="status">
            <Notice tone="success">
              {t(
                "Assignment saved as a draft. This is not operational approval.",
                "할당을 초안으로 저장했습니다. 이는 운영 승인이 아닙니다.",
              )}
            </Notice>
          </div>
        )}
        {refreshFailed && (
          <Notice tone="warning">
            {t(
              "Saved, but workspace refresh failed.",
              "저장했지만 워크스페이스를 새로고침하지 못했습니다.",
            )}{" "}
            <Button onClick={reload}>
              {t("Retry refresh", "새로고침 재시도")}
            </Button>
          </Notice>
        )}
      </form>
      <ContextPreviewPanel
        locale={locale}
        blocked={dirty || busy || missing || conflict}
        profile={baseline}
        contextKey={JSON.stringify([baseline, data.skills, data.mcp_servers])}
      />
      <Panel title={t("Execution boundary", "실행 경계")}>
        <p>
          {t(
            "LIVE execution, LLM inference, and MCP connection are unavailable in this workspace.",
            "이 워크스페이스에서는 LIVE 실행, LLM 추론, MCP 연결을 사용할 수 없습니다.",
          )}
        </p>
        <div className="button-row">
          <Button disabled>{t("Run agent", "에이전트 실행")}</Button>
          <Button disabled>{t("Connect MCP", "MCP 연결")}</Button>
        </div>
      </Panel>
    </div>
  );
}
