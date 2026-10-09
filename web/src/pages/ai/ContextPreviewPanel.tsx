import { useState } from "react";
import type { FormEvent } from "react";
import type {
  AgentProfileInput,
  ContextPreview,
  Locale,
} from "../../lib/contracts";
import { api } from "../../lib/api";
import { choose } from "../../lib/i18n";
import {
  Badge,
  Button,
  EmptyState,
  Field,
  Notice,
  Panel,
} from "../../components/ui";

export function ContextPreviewPanel({
  locale,
  blocked,
  profile,
  contextKey,
}: {
  locale: Locale;
  blocked: boolean;
  profile: AgentProfileInput;
  contextKey: string;
}) {
  const t = (en: string, ko: string) => choose(locale, en, ko);
  const [goal, setGoal] = useState("");
  const [busy, setBusy] = useState(false);
  const [receipt, setReceipt] = useState<{
    key: string;
    value: ContextPreview;
  } | null>(null);
  const [failure, setFailure] = useState<{
    key: string;
    message: string;
  } | null>(null);
  const requestKey = JSON.stringify([goal, locale, contextKey]);
  const result = !blocked && receipt?.key === requestKey ? receipt.value : null;
  const error = !blocked && failure?.key === requestKey ? failure.message : "";
  async function preview(event: FormEvent) {
    event.preventDefault();
    if (busy || blocked) return;
    setReceipt(null);
    setFailure(null);
    if (!goal.trim() || goal.length > 2000) {
      setFailure({
        key: requestKey,
        message: t(
          "Enter a review goal of 1–2000 characters, not only whitespace.",
          "공백만 있는 목표는 사용할 수 없습니다. 검토 목표를 1~2000자로 입력하세요.",
        ),
      });
      return;
    }
    setBusy(true);
    try {
      const assembled = await api.previewContext({ goal, locale });
      if (
        !assembled ||
        assembled.origin !== "deterministic_context_preview" ||
        assembled.execution_enabled !== false ||
        typeof assembled.prompt !== "string" ||
        !assembled.prompt.trim() ||
        JSON.stringify(assembled.skill_ids) !==
          JSON.stringify(profile.skill_ids) ||
        JSON.stringify(assembled.mcp_server_ids) !==
          JSON.stringify(profile.mcp_server_ids)
      ) {
        throw new Error(
          t(
            "The preview does not match this saved configuration. Refresh the workspace and try again.",
            "미리보기가 저장된 설정과 일치하지 않습니다. 워크스페이스를 새로고침하고 다시 시도하세요.",
          ),
        );
      }
      setReceipt({ key: requestKey, value: assembled });
    } catch (cause) {
      setFailure({
        key: requestKey,
        message:
          cause instanceof Error
            ? cause.message
            : t(
                "Unable to assemble context.",
                "컨텍스트를 조합할 수 없습니다.",
              ),
      });
    } finally {
      setBusy(false);
    }
  }
  return (
    <Panel
      title={t("Context preview", "컨텍스트 미리보기")}
      description={t(
        "Inspect the instructions before any future model integration.",
        "향후 모델 연동에 앞서 지침을 확인하세요.",
      )}
      actions={<Badge tone="info">{t("No inference", "추론 없음")}</Badge>}
    >
      <div className="form-stack">
        <Notice>
          {t(
            "Deterministic context assembly — not an LLM response or an executed test.",
            "결정적 컨텍스트 조합이며 LLM 응답이나 실행된 테스트가 아닙니다.",
          )}
        </Notice>
        <p className="muted">
          {t(
            "Uses the saved agent assignment and registered usage instructions. No model or MCP server is contacted.",
            "저장된 에이전트 할당과 등록된 사용 지침을 사용합니다. 모델이나 MCP 서버에 접속하지 않습니다.",
          )}
        </p>
        <form
          onSubmit={preview}
          className="form-stack"
          aria-label={t("Context preview request", "컨텍스트 미리보기 요청")}
        >
          <Field label={t("Review goal", "검토 목표")}>
            <textarea
              required
              rows={3}
              maxLength={2000}
              value={goal}
              disabled={busy}
              onChange={(event) => setGoal(event.target.value)}
            />
          </Field>
          <div className="ai-save-row">
            <small className="muted">{goal.length} / 2000</small>
            <Button
              type="submit"
              variant="primary"
              disabled={blocked || busy || !goal.trim()}
            >
              {busy
                ? t("Assembling context…", "컨텍스트 조합 중…")
                : t("Assemble context preview", "컨텍스트 미리보기 조합")}
            </Button>
          </div>
          {blocked && (
            <p className="muted">
              {t(
                "Save a valid assignment before previewing. Unsaved selections are not included.",
                "미리보기 전에 유효한 할당을 저장하세요. 저장하지 않은 선택은 포함되지 않습니다.",
              )}
            </p>
          )}
        </form>
        {error && (
          <Notice tone="danger">
            <strong>
              {t(
                "Context preview failed. Your goal is preserved.",
                "컨텍스트 미리보기에 실패했습니다. 목표 입력은 유지됩니다.",
              )}
            </strong>
            <p>{error}</p>
          </Notice>
        )}
        {result ? (
          <>
            <div role="status" className="muted">
              {t(
                `${result.skill_ids.length} Skills · ${result.mcp_server_ids.length} MCP instruction sets assembled`,
                `스킬 ${result.skill_ids.length}개 · MCP 지침 ${result.mcp_server_ids.length}개 조합됨`,
              )}
            </div>
            <div
              className="ai-preview-output"
              role="region"
              aria-label={t("Assembled instructions", "조합된 지침")}
              tabIndex={0}
            >
              <pre className="ai-instructions">{result.prompt}</pre>
            </div>
          </>
        ) : (
          !busy &&
          !error && (
            <EmptyState
              title={t(
                "No preview assembled yet",
                "아직 조합된 미리보기가 없습니다",
              )}
              description={t(
                "Enter a review goal to inspect the saved context. This does not start a test.",
                "검토 목표를 입력하여 저장된 컨텍스트를 확인하세요. 테스트를 시작하지 않습니다.",
              )}
            />
          )
        )}
      </div>
    </Panel>
  );
}
