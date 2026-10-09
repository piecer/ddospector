import type { Locale } from "../../lib/contracts";
import { Button, Field, Panel } from "../../components/ui";
import { choose } from "../../lib/i18n";
import type { AISettingsInput, AISettingsSnapshot } from "./types";
export type BindingsValue = Pick<
  AISettingsInput,
  "default_profile_id" | "agent_profile_id"
>;
export function Bindings({
  snapshot,
  value,
  disabled,
  dirty,
  locale,
  onChange,
  onSave,
}: {
  snapshot: AISettingsSnapshot;
  value: BindingsValue;
  disabled: boolean;
  dirty: boolean;
  locale: Locale;
  onChange: (value: BindingsValue) => void;
  onSave: () => void;
}) {
  const t = (en: string, ko: string) => choose(locale, en, ko);
  return (
    <Panel
      title={t("Draft bindings", "초안 바인딩")}
      description={t(
        "No implicit default. An unbound review agent follows the default draft, which may also be unset.",
        "기본 프로필은 자동 선택되지 않습니다. 미지정 검토 에이전트는 기본 초안을 따르며, 기본 초안도 미지정일 수 있습니다.",
      )}
    >
      <form
        className="form-stack"
        onSubmit={(e) => {
          e.preventDefault();
          if (!disabled && dirty) onSave();
        }}
      >
        <fieldset className="page-fieldset form-grid" disabled={disabled}>
          <Field label={t("Default draft", "기본 초안")}>
            <select
              value={value.default_profile_id ?? ""}
              onChange={(e) =>
                onChange({
                  ...value,
                  default_profile_id: e.target.value || null,
                })
              }
            >
              <option value="">{t("Not selected", "선택 안 됨")}</option>
              {snapshot.profiles.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label={t("Review-agent draft", "검토 에이전트 초안")}>
            <select
              value={value.agent_profile_id ?? ""}
              onChange={(e) =>
                onChange({ ...value, agent_profile_id: e.target.value || null })
              }
            >
              <option value="">
                {t("Follow default", "기본 초안 따르기")}
              </option>
              {snapshot.profiles.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </Field>
        </fieldset>
        <div className="button-row">
          <Button type="submit" variant="primary" disabled={disabled || !dirty}>
            {t("Save bindings", "바인딩 저장")}
          </Button>
          {dirty && (
            <Button
              disabled={disabled}
              onClick={() =>
                onChange({
                  default_profile_id: snapshot.default_profile_id,
                  agent_profile_id: snapshot.agent_profile_id,
                })
              }
            >
              {t("Discard binding changes", "바인딩 변경 취소")}
            </Button>
          )}
        </div>
        {dirty && (
          <p className="muted">
            {t(
              "Save or discard binding changes before editing profiles.",
              "프로필 편집 전에 바인딩 변경을 저장하거나 취소하세요.",
            )}
          </p>
        )}
      </form>
    </Panel>
  );
}
