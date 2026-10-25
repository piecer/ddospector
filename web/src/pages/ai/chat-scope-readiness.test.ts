// Harness source-contract and synthetic DOM controls, not browser acceptance.
import { readFileSync } from "node:fs";
import ts from "typescript";
import { expect, it } from "vitest";

const source = ts.createSourceFile(
  "chat-tools.case.ts",
  readFileSync("e2e/chat-tools.case.ts", "utf8"),
  ts.ScriptTarget.Latest,
  true,
);
const printer = ts.createPrinter({ removeComments: true });
function printed(node: ts.Node, file = source) {
  return printer.printNode(ts.EmitHint.Unspecified, node, file);
}
function statement(text: string) {
  const file = ts.createSourceFile(
    "expected.ts",
    text,
    ts.ScriptTarget.Latest,
    true,
  );
  return printed(file.statements[0], file);
}
const scopes = [
  { branch: "skillCase", name: "스킬 생성", value: "skill_create_v3" },
  { branch: "targetCase", name: "대상 생성", value: "target_create_v2" },
];

it.each(scopes)(
  "$branch awaits its option's disabled=false guard before selecting $value",
  ({ branch, name, value }) => {
    const selections: { block: ts.Block; index: number }[] = [];
    function visit(node: ts.Node) {
      if (
        ts.isIfStatement(node) &&
        ts.isIdentifier(node.expression) &&
        node.expression.text === branch &&
        ts.isBlock(node.thenStatement)
      ) {
        const block = node.thenStatement;
        block.statements.forEach((item, index) => {
          if (
            printed(item) === statement(`await scope.selectOption("${value}");`)
          )
            selections.push({ block, index });
        });
      }
      ts.forEachChild(node, visit);
    }
    visit(source);
    expect(selections).toHaveLength(1);
    const { block, index } = selections[0];
    expect(block.statements.map((item) => printed(item))).toContain(
      statement('const scope = page.getByTestId("chat-tool-scope");'),
    );
    expect(index).toBeGreaterThan(0);
    // Compare parsed statements, not a substring that could match a comment,
    // an unawaited assertion, another branch, or a guard after selection.
    expect(printed(block.statements[index - 1])).toBe(
      statement(
        `await expect(page.getByRole("option", { name: "${name}" }))` +
          '.toHaveJSProperty("disabled", false);',
      ),
    );
  },
);

it.each(scopes)(
  "$branch option disabled property stays distinct from its label's enabled select",
  ({ name, value }) => {
    const label = document.createElement("label");
    const select = document.createElement("select");
    const option = document.createElement("option");
    option.textContent = name;
    option.value = value;
    option.disabled = true;
    select.append(option);
    label.append(select);

    // Synthetic negative/positive controls only; Playwright is not executed.
    expect(label.control).toBe(select);
    expect(select.disabled).toBe(false);
    expect(option.disabled).toBe(true);
    option.disabled = false;
    expect(option.disabled).toBe(false);
    expect(select.disabled).toBe(false);
  },
);
