import type { Locale, Skill } from "../../lib/contracts";
import { choose, text } from "../../lib/i18n";
import { Badge, Notice } from "../../components/ui";

export function categoryLabel(
  value: Skill["category"],
  locale: Locale,
): string {
  return (
    {
      planning: choose(locale, "Planning", "계획"),
      measurement: choose(locale, "Measurement", "측정"),
      analysis: choose(locale, "Analysis", "분석"),
    }[value] ?? value
  );
}

export function SkillDetails({
  skill,
  locale,
  showName = false,
}: {
  skill: Skill;
  locale: Locale;
  showName?: boolean;
}) {
  const t = (en: string, ko: string) => choose(locale, en, ko);
  return (
    <div className="ai-skill-details form-stack">
      {showName && <h3>{text(skill.name, locale)}</h3>}
      <div className="chips">
        <Badge>{categoryLabel(skill.category, locale)}</Badge>
        <Badge>{skill.version}</Badge>
        <Badge>
          {skill.status === "draft"
            ? t("User draft", "사용자 초안")
            : t("Built-in template", "기본 템플릿")}
        </Badge>
        <code>{skill.id}</code>
      </div>
      <p>{text(skill.description, locale)}</p>
      <Notice tone="warning">
        {t(
          "Guidance only: these instructions grant no approval, tool access, or execution permission.",
          "지침 전용입니다. 이 지침은 승인, 도구 접근 권한, 실행 권한을 부여하지 않습니다.",
        )}
      </Notice>
      <section>
        <h3>{t("Required capabilities", "필요 기능")}</h3>
        {skill.required_capabilities.length ? (
          <>
            <p className="muted">
              {t(
                "Declared prerequisites, not verified server capabilities.",
                "선언된 사전 조건이며 검증된 서버 기능이 아닙니다.",
              )}
            </p>
            <ul>
              {skill.required_capabilities.map((value) => (
                <li key={value}>
                  <code>{value}</code>
                </li>
              ))}
            </ul>
          </>
        ) : (
          <p className="muted">
            {t(
              "No capabilities declared; availability is not verified.",
              "선언된 필요 기능이 없습니다. 사용 가능 여부는 검증되지 않았습니다.",
            )}
          </p>
        )}
      </section>
      <section>
        <h3>
          {t("Declared operations · guidance only", "명시된 작업 · 지침 전용")}
        </h3>
        {skill.allowed_operations.length ? (
          <ul>
            {skill.allowed_operations.map((value) => (
              <li key={value}>
                <code>{value}</code>
              </li>
            ))}
          </ul>
        ) : (
          <p className="muted">
            {t(
              "No operations declared. This does not grant permission.",
              "명시된 작업이 없습니다. 이는 권한을 부여하지 않습니다.",
            )}
          </p>
        )}
      </section>
      <section>
        <h3>{t("Safety rules", "안전 규칙")}</h3>
        {skill.safety_rules.length ? (
          <ul>
            {skill.safety_rules.map((rule, index) => (
              <li key={index}>{text(rule, locale)}</li>
            ))}
          </ul>
        ) : (
          <p className="muted">
            {t(
              "No Skill-specific safety rules supplied. Workspace safeguards still apply.",
              "스킬별 안전 규칙이 제공되지 않았습니다. 워크스페이스 보호 조치는 계속 적용됩니다.",
            )}
          </p>
        )}
      </section>
      <section>
        <h3>{t("Full instructions", "전체 지침")}</h3>
        <pre className="ai-instructions">
          {text(skill.instructions, locale)}
        </pre>
      </section>
    </div>
  );
}
