import { useRef, useState } from "react";
import type {
  PageProps,
  Skill,
  SkillSelection,
  WorkspaceSnapshot,
  Locale,
} from "../../lib/contracts";
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
import { useSkillReadback } from "./useSkillReadback";
import { SkillDraftForm } from "./SkillDraftForm";
import { categoryLabel, SkillDetails } from "./SkillDetails";

export function SkillsPage({
  data,
  locale,
  refresh,
  skillSelection,
}: PageProps) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detailsOwner, setDetailsOwner] = useState(skillSelection);
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
      <SelectedSkillReadback
        selection={skillSelection}
        workspace={data}
        locale={locale}
      />
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
                  <Button
                    onClick={() => {
                      setDetailsOwner(skillSelection);
                      setSelectedId(skill.id);
                    }}
                  >
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
        open={selectedId !== null && detailsOwner === skillSelection}
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

/** Separate inspected bytes: never merge a receipt or inspection into manual drafts. */
export function SelectedSkillReadback({
  selection,
  workspace,
  locale,
}: {
  selection?: SkillSelection;
  workspace: WorkspaceSnapshot | null;
  locale: Locale;
}) {
  const [dismissed, setDismissed] = useState<SkillSelection>();
  const open = !!selection && dismissed !== selection;
  const read = useSkillReadback(selection, workspace, open);
  const trigger = useRef<HTMLButtonElement>(null);
  const t = (en: string, ko: string) => choose(locale, en, ko);
  const labels = {
    loading: t("Reading selected Skill…", "선택한 스킬 읽는 중…"),
    "receipt-confirmed": t(
      "Receipt-confirmed record. This does not independently confirm the saved audit.",
      "영수증과 레코드 일치. 저장된 감사 기록의 독립 검증은 아닙니다.",
    ),
    "current-only": t(
      "Current record only — no saved receipt expectation.",
      "현재 레코드만 표시 — 저장 영수증 기대값 없음.",
    ),
    discrepancy: t(
      "Discrepancy — missing, changed or older than the receipt. Saved remains a historical fact.",
      "불일치 — 누락, 변경 또는 영수증보다 이전 상태입니다. 저장 사실은 보존됩니다.",
    ),
    unavailable: t(
      "Inspection unavailable. No automatic retry; Saved is not erased.",
      "검사 불가. 자동 재시도하지 않으며 저장 사실은 지워지지 않습니다.",
    ),
    stale: t("Inspection stale / unverified.", "오래된 검사 / 미확인."),
  };
  if (!selection) return null;
  function close() {
    read.cancel();
    setDismissed(selection);
  }
  return (
    <section className="ai-page ai-selected-skill">
      <p
        id="skill-readback-status"
        data-testid="skill-readback-status"
        data-readback={read.state}
        role="status"
      >
        {labels[read.state]}
      </p>
      <code>{selection.id}</code>
      <button
        type="button"
        className="button button-secondary"
        ref={trigger}
        data-testid="skill-readback-open"
        onClick={() => {
          setDismissed(undefined);
        }}
      >
        {t("Open selected Skill", "선택한 스킬 열기")}
      </button>
      <Dialog
        open={open}
        title={t("Selected Skill details", "선택한 스킬 상세")}
        onClose={close}
        recoveryOnly
        restoreFocusTo={trigger}
      >
        <div className="ai-page form-stack">
          <p>{labels[read.state]}</p>
          <Button disabled={read.pending} onClick={read.refresh}>
            {t(
              "Read selected Skill again (GET only)",
              "선택한 스킬 다시 읽기 (GET 전용)",
            )}
          </Button>
          {read.pending && (
            <Button onClick={read.cancel}>
              {t("Cancel inspection", "검사 취소")}
            </Button>
          )}
          {read.skill && (
            <SkillDetails skill={read.skill} locale={locale} showName />
          )}
        </div>
      </Dialog>
    </section>
  );
}
