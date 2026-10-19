// SYNTHETIC strict GET responses exercise the shipped components/decoder.
// Harness-binding regression only: not native producer or browser acceptance.
import { readFileSync } from "node:fs";
import ts from "typescript";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { SkillsPage, SelectedSkillReadback } from "./SkillsPage";
import { aiFixture } from "./testFixtures";
import {
  draft,
  skillInspection,
  skillCall,
  skillTranscript,
  skillInput,
} from "./chat-skill-test-fixtures";
import { response, turn, tid } from "./chat-test-fixtures";
import { ToolRecords } from "./ToolRecords";
import { parseTurn } from "./chat-wire";

const e2e = readFileSync("e2e/chat-tools.case.ts", "utf8");
function statementBefore(name: string) {
  const source = ts.createSourceFile(
    "case.ts",
    e2e,
    ts.ScriptTarget.Latest,
    true,
  );
  let previous: string | undefined;
  function visit(node: ts.Node) {
    if (ts.isBlock(node)) {
      node.statements.forEach((statement, index) => {
        if (
          ts.isVariableStatement(statement) &&
          statement.declarationList.declarations.some(
            (declaration) =>
              ts.isIdentifier(declaration.name) &&
              declaration.name.text === name,
          )
        )
          previous = node.statements[index - 1]?.getText(source);
      });
    }
    ts.forEachChild(node, visit);
  }
  visit(source);
  expect(previous).toBeDefined();
  return previous!;
}
const selection = () => ({
  id: draft.id,
  expectation: { skill: structuredClone(draft), after_revision: 3 },
});
function strictInspection(value = skillInspection) {
  const fetch = vi.fn(async (url: string, init?: RequestInit) => {
    expect(url).toBe(`/api/v1/chat/tools/skills/${draft.id}`);
    expect(init?.method).toBe("GET");
    expect(init?.body).toBeUndefined();
    return response(value);
  });
  vi.stubGlobal("fetch", fetch);
  return fetch;
}
async function confirmed() {
  await waitFor(() =>
    expect(screen.getByTestId("skill-readback-status")).toHaveAttribute(
      "data-readback",
      "receipt-confirmed",
    ),
  );
}
function escapeDialog() {
  // jsdom's cancel event is the browser Escape seam, not a keyboard proof.
  fireEvent(screen.getByRole("dialog"), new Event("cancel", { bubbles: true }));
}
afterEach(() => {
  vi.unstubAllGlobals();
  document.documentElement.lang = "en";
});

it.each(["en", "ko"] as const)(
  "keeps full inert detail and localized public controls through current-only/new handoff (%s)",
  async (locale) => {
    // Deliberately synthetic, long strict response; not a producer-positive corpus.
    const literal =
      "  SYNTHETIC <script>not authority</script> [link](javascript:alert(1))\n" +
      "Long literal instruction / 긴 지침 🌍\t".repeat(48) +
      "\r\nFULL-INSTRUCTION-TAIL-끝  ";
    const skill = {
      ...structuredClone(draft),
      instructions: { en: literal, ko: literal },
    };
    const fetch = strictInspection({ ...skillInspection, skill });
    const selected = {
      id: skill.id,
      expectation: { skill, after_revision: 3 },
    };
    document.documentElement.lang = locale;
    const ui = render(
      <SelectedSkillReadback
        selection={selected}
        workspace={null}
        locale={locale}
      />,
    );
    await confirmed();
    const dialog = screen.getByRole("dialog", {
      name: locale === "en" ? "Selected Skill details" : "선택한 스킬 상세",
    });
    expect(dialog.querySelector(".ai-instructions")?.textContent).toBe(literal);
    expect(dialog.textContent).toContain("FULL-INSTRUCTION-TAIL-끝");
    expect(dialog.textContent).toContain(skill.id);
    expect(dialog.textContent).toContain(skill.version);
    expect(dialog.textContent).toContain(skill.description[locale]);
    expect(
      within(dialog).getByRole("heading", {
        name: locale === "en" ? "Full instructions" : "전체 지침",
      }),
    ).toBeVisible();
    expect(
      within(dialog).getByRole("heading", {
        name: locale === "en" ? "Safety rules" : "안전 규칙",
      }),
    ).toBeVisible();
    for (const rule of skill.safety_rules)
      expect(dialog.textContent).toContain(rule[locale]);
    expect(dialog.textContent).toContain(
      locale === "en"
        ? "No capabilities declared"
        : "선언된 필요 기능이 없습니다",
    );
    expect(dialog.textContent).toContain(
      locale === "en" ? "No operations declared" : "명시된 작업이 없습니다",
    );
    expect(dialog.textContent).toContain(
      locale === "en" ? "Receipt-confirmed record." : "영수증과 레코드 일치.",
    );
    expect(dialog.querySelector("script, a, img")).toBeNull();
    const readAgain = within(dialog).getByRole("button", {
      name:
        locale === "en"
          ? "Read selected Skill again (GET only)"
          : "선택한 스킬 다시 읽기 (GET 전용)",
    });
    expect(readAgain).toBeEnabled();
    fireEvent.click(readAgain);
    await confirmed();
    expect(fetch).toHaveBeenCalledTimes(2);
    fireEvent.click(
      within(dialog).getByRole("button", {
        name: locale === "en" ? "Close dialog" : "대화상자 닫기",
      }),
    );
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByTestId("skill-readback-open")).toHaveFocus();
    // New selection identity reopens; ID alone never reacquires receipt authority.
    ui.rerender(
      <SelectedSkillReadback
        selection={{ id: skill.id }}
        workspace={null}
        locale={locale}
      />,
    );
    await waitFor(() =>
      expect(screen.getByTestId("skill-readback-status")).toHaveAttribute(
        "data-readback",
        "current-only",
      ),
    );
    expect(screen.getByRole("dialog").textContent).toContain(
      locale === "en" ? "Current record only" : "현재 레코드만 표시",
    );
    expect(fetch).toHaveBeenCalledTimes(3);
    ui.rerender(
      <SelectedSkillReadback
        selection={{ ...selected }}
        workspace={null}
        locale={locale}
      />,
    );
    await confirmed();
    expect(fetch).toHaveBeenCalledTimes(4);
    expect(fetch.mock.calls.every(([, init]) => init?.method === "GET")).toBe(
      true,
    );
  },
);

it.each(["en", "ko"] as const)(
  "binds exact approval to the delivered literal field markup (%s)",
  async (locale) => {
    const fetch = vi.fn(async (url: string, init?: RequestInit) => {
      expect(url).toBe(`/api/v1/chat/turns/${tid}/tools`);
      expect(init?.method).toBe("GET");
      return response({ ...skillTranscript, calls: [skillCall] });
    });
    vi.stubGlobal("fetch", fetch);
    render(
      <ToolRecords
        turn={parseTurn(turn)}
        locale={locale}
        enabled
        viewEpoch={0}
        canWrite
      />,
    );
    const card = await screen.findByTestId(
      `chat-tool-proposal-${skillCall.id}`,
    );
    const binding = e2e.match(
      /const displayedAfter = await card[\s\S]*?\.last\(\)\s*\.locator\("([^"]+)"\)/,
    );
    expect(binding).not.toBeNull();
    const after = card.querySelectorAll(".chat-tool-diff > div")[1];
    const fields = Array.from(after.querySelectorAll(binding![1]));
    const displayed = Object.fromEntries(
      fields.map((field) => [
        field.querySelector("dt")?.textContent,
        field.querySelector("dd > pre")?.textContent,
      ]),
    );
    expect(displayed).toEqual(skillInput);
    expect(fields).toHaveLength(4);
    expect(e2e).toContain('field.querySelector("dt")!.textContent');
    expect(e2e).toContain('field.querySelector("dd > pre")!.textContent');
    expect(card.textContent).toContain(skillCall.proposal.digest);
    expect(card.textContent).toContain(skillCall.proposal.expires_at);
    expect(card.textContent).toContain(
      String(skillCall.proposal.expected_draft_revision),
    );
    expect(card.querySelector("script, a, img")).toBeNull();
    expect(
      screen.getByTestId(`chat-tool-approve-${skillCall.id}`),
    ).toBeEnabled();
    expect(screen.getByTestId(`chat-tool-deny-${skillCall.id}`)).toBeEnabled();
    expect(
      screen.queryByTestId(`chat-tool-view-saved-${skillCall.id}`),
    ).toBeNull();
    expect(fetch.mock.calls.every(([, init]) => init?.method === "GET")).toBe(
      true,
    );
  },
);

it("binds the prepared E2E reopen selector to the actual stable focus-return control", async () => {
  const fetch = strictInspection();
  render(<SkillsPage {...aiFixture()} skillSelection={selection()} />);
  await confirmed();
  expect(fetch).toHaveBeenCalledTimes(1);
  escapeDialog();
  expect(screen.queryByRole("dialog")).toBeNull();
  const binding = e2e.match(
    /page\.getByTestId\("(skill-[^"]+-open)"\)\.click\(\)/,
  );
  expect(binding).not.toBeNull();
  const open = screen.getByTestId(binding![1]);
  expect(open).toHaveFocus();
  expect(open).toHaveAccessibleName("Open selected Skill");
  fireEvent.click(open);
  await confirmed();
  expect(screen.getByRole("dialog")).toBeVisible();
  expect(fetch).toHaveBeenCalledTimes(2);
  escapeDialog();
  expect(open).toHaveFocus();
  await act(async () => {});
  expect(fetch).toHaveBeenCalledTimes(2);
  // Each keyboard reopen owns a fresh GET. Settle it before the next Escape,
  // rather than cancelling a live read while the next locale opens another.
  expect(
    /getByTestId\("skill-readback-open"\)\.press\("Enter"\);\s*await expect\(\s*page\.getByTestId\("skill-readback-status"\),?\s*\)\.toHaveAttribute\("data-readback", "receipt-confirmed"\)/.test(
      e2e,
    ),
  ).toBe(true);
});

it("uses a focusable public read-again control before the E2E keyboard scroll", async () => {
  strictInspection();
  render(<SkillsPage {...aiFixture()} skillSelection={selection()} />);
  await confirmed();
  const dialog = screen.getByRole("dialog");
  const readAgain = within(dialog).getByRole("button", {
    name: "Read selected Skill again (GET only)",
  });
  readAgain.focus();
  expect(readAgain).toHaveFocus();
  const instructions = dialog.querySelector<HTMLElement>(".ai-instructions")!;
  instructions.focus();
  // The shipped pre is plain text, not a keyboard focus target.
  expect(instructions).not.toHaveFocus();
  expect(readAgain).toHaveFocus();
  expect(e2e).not.toContain(
    'await dialog.locator(".ai-instructions").focus();',
  );
  expect(e2e).toContain("await expect(readAgainControl).toBeFocused();");
});

it("keeps the final reopened dialog open for the E2E's GET-only read-again", async () => {
  const fetch = strictInspection();
  render(
    <SkillsPage {...aiFixture()} locale="ko" skillSelection={selection()} />,
  );
  await confirmed();
  escapeDialog();
  expect(
    screen.queryByRole("button", { name: "선택한 스킬 다시 읽기 (GET 전용)" }),
  ).toBeNull();
  fireEvent.click(screen.getByTestId("skill-readback-open"));
  await confirmed();
  const beforeReadAgain = statementBefore("writesBeforeRetry");
  // Replay the prepared harness's final control order against the real dialog.
  if (
    beforeReadAgain.trimEnd().endsWith('await page.keyboard.press("Escape");')
  )
    escapeDialog();
  const dialog = screen.getByRole("dialog");
  const readAgain = within(dialog).getByRole("button", {
    name: "선택한 스킬 다시 읽기 (GET 전용)",
  });
  expect(readAgain).toBeEnabled();
  expect(e2e).not.toContain('getByTestId("skill-readback-retry")');
  expect(e2e).toContain('name: "선택한 스킬 다시 읽기 (GET 전용)"');
  const reads = fetch.mock.calls.length;
  fireEvent.click(readAgain);
  await confirmed();
  expect(fetch).toHaveBeenCalledTimes(reads + 1);
  expect(fetch.mock.calls.every(([, init]) => init?.method === "GET")).toBe(
    true,
  );
  escapeDialog();
  expect(screen.getByTestId("skill-readback-open")).toHaveFocus();
});
