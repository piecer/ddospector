import { useState } from "react";
import type { FormEvent } from "react";
import type { Locale, Skill, SkillInput } from "../../lib/contracts";
import { api } from "../../lib/api";
import { choose } from "../../lib/i18n";
import { Badge, Button, Field, Notice, Panel } from "../../components/ui";

const emptyDraft: SkillInput = {
  name: "",
  description: "",
  instructions: "",
  category: "planning",
};

export function SkillDraftForm({
  locale,
  onCreated,
  refresh,
}: {
  locale: Locale;
  onCreated: (skill: Skill) => void;
  refresh: () => Promise<void>;
}) {
  const t = (en: string, ko: string) => choose(locale, en, ko);
  const [draft, setDraft] = useState<SkillInput>(emptyDraft);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const [refreshFailed, setRefreshFailed] = useState(false);
  const dirty =
    draft.name !== "" ||
    draft.description !== "" ||
    draft.instructions !== "" ||
    draft.category !== "planning";
  function edit<K extends keyof SkillInput>(key: K, value: SkillInput[K]) {
    setDraft((current) => ({ ...current, [key]: value }));
    setSaved(false);
    setError("");
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
    if (busy) return;
    if (
      !draft.name.trim() ||
      draft.name.length > 120 ||
      !draft.description.trim() ||
      draft.description.length > 1000 ||
      !draft.instructions.trim() ||
      draft.instructions.length > 8000
    ) {
      setError(
        t(
          "Use non-blank text within the field limits.",
          "빈칸이 아닌 텍스트를 각 필드의 글자 수 제한 안에서 입력하세요.",
        ),
      );
      return;
    }
    setBusy(true);
    setError("");
    setSaved(false);
    try {
      const skill = await api.createSkill(draft);
      onCreated(skill);
      setDraft(emptyDraft);
      setSaved(true);
      await reload();
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : t("Unable to save this draft.", "초안을 저장할 수 없습니다."),
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <Panel
      title={t("Create a custom Skill", "사용자 스킬 만들기")}
      description={t(
        "Write procedures, prerequisites, evidence requirements, and safety guidance. Original text is kept in both languages; it is not translated.",
        "절차, 사전 조건, 증거 요구 사항, 안전 지침을 작성하세요. 입력 원문은 두 언어에 그대로 보존되며 번역되지 않습니다.",
      )}
      actions={
        dirty ? (
          <Badge tone="warning">
            {t("Unsaved draft", "저장하지 않은 초안")}
          </Badge>
        ) : (
          <Badge>{t("Draft only", "초안 전용")}</Badge>
        )
      }
    >
      <form
        onSubmit={save}
        className="form-stack"
        aria-label={t("Custom Skill draft", "사용자 스킬 초안")}
      >
        <fieldset disabled={busy} className="ai-fieldset form-stack">
          <Field label={t("Skill name", "스킬 이름")}>
            <input
              required
              maxLength={120}
              value={draft.name}
              onChange={(event) => edit("name", event.target.value)}
            />
          </Field>
          <Field label={t("Description", "설명")}>
            <textarea
              required
              maxLength={1000}
              rows={2}
              value={draft.description}
              onChange={(event) => edit("description", event.target.value)}
            />
          </Field>
          <Field label={t("Draft category", "초안 분류")}>
            <select
              value={draft.category}
              onChange={(event) =>
                edit("category", event.target.value as Skill["category"])
              }
            >
              <option value="planning">{t("Planning", "계획")}</option>
              <option value="measurement">{t("Measurement", "측정")}</option>
              <option value="analysis">{t("Analysis", "분석")}</option>
            </select>
          </Field>
          <Field label={t("Instructions", "지침")}>
            <textarea
              required
              maxLength={8000}
              rows={9}
              value={draft.instructions}
              onChange={(event) => edit("instructions", event.target.value)}
            />
          </Field>
          <small className="muted">
            {draft.instructions.length} / 8000 ·{" "}
            {t(
              "Plain text only. Never include secrets or credentials.",
              "일반 텍스트 전용입니다. 비밀 정보나 자격 증명을 입력하지 마세요.",
            )}
          </small>
          <Button type="submit" variant="primary">
            {busy
              ? t("Saving draft…", "초안 저장 중…")
              : t("Save Skill draft", "스킬 초안 저장")}
          </Button>
        </fieldset>
        {error && (
          <Notice tone="danger">
            <strong>
              {t(
                "Draft not saved. Your inputs are preserved.",
                "초안을 저장하지 못했습니다. 입력 내용은 유지됩니다.",
              )}
            </strong>
            <p>{error}</p>
          </Notice>
        )}
        {saved && (
          <div role="status">
            <Notice tone="success">
              {t(
                "Skill draft saved. No execution permission granted.",
                "스킬 초안을 저장했습니다. 실행 권한은 부여되지 않았습니다.",
              )}
            </Notice>
          </div>
        )}
        {refreshFailed && (
          <Notice tone="warning">
            {t(
              "Saved, but workspace refresh failed. Do not create the same draft again.",
              "저장했지만 워크스페이스를 새로고침하지 못했습니다. 같은 초안을 다시 만들지 마세요.",
            )}{" "}
            <Button onClick={reload}>
              {t("Retry refresh", "새로고침 재시도")}
            </Button>
          </Notice>
        )}
      </form>
    </Panel>
  );
}
