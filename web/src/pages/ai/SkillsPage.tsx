import { useState } from "react";
import type { PageProps, Skill } from "../../lib/contracts";
import { choose, text } from "../../lib/i18n";
import {
  Badge,
  Button,
  Dialog,
  EmptyState,
  Field,
  Notice,
  PageHeader,
  Panel,
} from "../../components/ui";
import { SkillDraftForm } from "./SkillDraftForm";
import { categoryLabel, SkillDetails } from "./SkillDetails";

export function SkillsPage({ data, locale, refresh }: PageProps) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [created, setCreated] = useState<Skill[]>([]);
  const [query, setQuery] = useState("");
  const [categoryFilter, setCategoryFilter] = useState("all");
  const [sourceFilter, setSourceFilter] = useState("all");
  const t = (en: string, ko: string) => choose(locale, en, ko);
  const skills = [
    ...data.skills,
    ...created.filter(
      (skill) => !data.skills.some((existing) => existing.id === skill.id),
    ),
  ];
  const selected = skills.find((skill) => skill.id === selectedId);
  const filtered = skills.filter(
    (skill) =>
      (categoryFilter === "all" || skill.category === categoryFilter) &&
      (sourceFilter === "all" || skill.status === sourceFilter) &&
      [
        skill.id,
        text(skill.name, locale),
        text(skill.description, locale),
        text(skill.instructions, locale),
        ...skill.required_capabilities,
      ]
        .join(" ")
        .toLocaleLowerCase()
        .includes(query.trim().toLocaleLowerCase()),
  );
  function clearFilters() {
    setQuery("");
    setCategoryFilter("all");
    setSourceFilter("all");
  }

  return (
    <div className="page-stack ai-page">
      <PageHeader
        eyebrow={t("AI & governance", "AI 및 거버넌스")}
        title={t("Skills", "스킬")}
        description={t(
          "Versioned instructions for planning, MCP usage, and evidence review.",
          "계획, MCP 사용, 증거 검토를 위한 버전별 지침입니다.",
        )}
      />
      <Notice tone="warning">
        {t(
          "Skills are guidance, not approval authority. MCP bindings and the Safety Gate remain authoritative. Saving instructions does not authorize execution.",
          "스킬은 지침이며 승인 권한이 아닙니다. MCP 바인딩과 Safety Gate의 권한을 대체하지 않습니다. 지침을 저장해도 실행은 승인되지 않습니다.",
        )}
      </Notice>
      <div className="ai-skills-layout">
        <Panel title={t("Instruction library", "지침 라이브러리")}>
          <div className="ai-filters">
            <Field label={t("Search Skills", "스킬 검색")}>
              <input
                type="search"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
              />
            </Field>
            <Field label={t("Category", "분류")}>
              <select
                value={categoryFilter}
                onChange={(event) => setCategoryFilter(event.target.value)}
              >
                <option value="all">{t("All categories", "모든 분류")}</option>
                {(["planning", "measurement", "analysis"] as const).map(
                  (value) => (
                    <option key={value} value={value}>
                      {categoryLabel(value, locale)}
                    </option>
                  ),
                )}
              </select>
            </Field>
            <Field label={t("Source", "출처")}>
              <select
                value={sourceFilter}
                onChange={(event) => setSourceFilter(event.target.value)}
              >
                <option value="all">{t("All sources", "모든 출처")}</option>
                <option value="template">
                  {t("Built-in template", "기본 템플릿")}
                </option>
                <option value="draft">{t("User draft", "사용자 초안")}</option>
              </select>
            </Field>
          </div>
          <p role="status" className="muted">
            {t(
              `${filtered.length} of ${skills.length} instructions`,
              `전체 ${skills.length}개 중 ${filtered.length}개 지침`,
            )}
          </p>
          {!skills.length ? (
            <EmptyState
              title={t("No Skills yet", "아직 스킬이 없습니다")}
              description={t(
                "No instructions were returned by the workspace. Create a user draft to get started.",
                "워크스페이스에서 반환된 지침이 없습니다. 사용자 초안을 만들어 시작하세요.",
              )}
            />
          ) : !filtered.length ? (
            <EmptyState
              title={t("No matching instructions", "일치하는 지침이 없습니다")}
              description={t(
                "Try another search or clear your filters.",
                "검색어를 바꾸거나 필터를 초기화하세요.",
              )}
              action={
                <Button onClick={clearFilters}>
                  {t("Clear filters", "필터 초기화")}
                </Button>
              }
            />
          ) : (
            <ul className="ai-catalog">
              {filtered.map((skill) => (
                <li className="item-card" key={skill.id}>
                  <div className="chips">
                    <Badge>{categoryLabel(skill.category, locale)}</Badge>
                    <Badge
                      tone={skill.status === "draft" ? "warning" : "neutral"}
                    >
                      {skill.status === "draft"
                        ? t("User draft", "사용자 초안")
                        : t("Built-in template", "기본 템플릿")}
                    </Badge>
                    <span className="mono">{skill.version}</span>
                  </div>
                  <h3>{text(skill.name, locale)}</h3>
                  <p className="muted">{text(skill.description, locale)}</p>
                  <Button onClick={() => setSelectedId(skill.id)}>
                    {t("View instructions", "지침 보기")}
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </Panel>
        <SkillDraftForm
          locale={locale}
          refresh={refresh}
          onCreated={(skill) => {
            setCreated((current) => [...current, skill]);
            clearFilters();
          }}
        />
      </div>
      <Dialog
        open={selectedId !== null}
        title={
          selected
            ? text(selected.name, locale)
            : t("Skill details", "스킬 상세")
        }
        onClose={() => setSelectedId(null)}
      >
        {selected ? (
          <SkillDetails skill={selected} locale={locale} />
        ) : (
          <Notice tone="warning">
            {t(
              "This Skill is no longer available in the current workspace.",
              "현재 워크스페이스에서 이 스킬을 더 이상 사용할 수 없습니다.",
            )}
          </Notice>
        )}
      </Dialog>
    </div>
  );
}
