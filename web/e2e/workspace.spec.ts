import { expect, test } from "@playwright/test";
import type { Page, TestInfo } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { navigation } from "../src/lib/navigation";
import type { WorkspaceSnapshot, ContextPreview } from "../src/lib/contracts";
import {
  unexpectedConsole,
  type MetadataResponse,
} from "../src/test/chat-metadata-console";

test.beforeAll(async ({ request }) => {
  const health = await request.get("/api/v1/health", { timeout: 5000 });
  expect(health.status()).toBe(200);
  expect(await health.json()).toEqual({
    status: "ok",
    version: "0.1.0-ui",
    mode: "OFFLINE",
  });
});

function diagnostics(page: Page, expectUnconfiguredStorage = false) {
  const errors: string[] = [];
  const consoleErrors: { text: string; url: string }[] = [];
  const failedResponses: {
    url: string;
    status: number;
    body: unknown;
    fact: MetadataResponse;
  }[] = [];
  const metadataResponses: MetadataResponse[] = [];
  const pending: Promise<void>[] = [];
  const requests: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error")
      consoleErrors.push({ text: message.text(), url: message.location().url });
  });
  page.on("response", (response) => {
    const fact: MetadataResponse = {
      order: metadataResponses.length,
      url: response.url(),
      method: response.request().method(),
      status: response.status(),
    };
    metadataResponses.push(fact);
    if (response.status() < 400) return;
    pending.push(
      (async () => {
        try {
          const body: unknown = await response.json();
          if (
            body !== null &&
            typeof body === "object" &&
            "code" in body &&
            typeof body.code === "string"
          )
            fact.code = body.code;
          failedResponses.push({
            url: response.url(),
            status: response.status(),
            body,
            fact,
          });
        } catch {
          errors.push(`Unreadable failed response: ${response.url()}`);
        }
      })(),
    );
  });
  page.on("request", (request) => requests.push(request.url()));
  return {
    requests,
    async assertHealthy() {
      await Promise.all(pending);
      expect(errors).toEqual([]);
      const remainingResponses = failedResponses.filter((entry) => {
        const exactBusy =
          entry.status === 429 &&
          JSON.stringify(entry.body) ===
            JSON.stringify({
              code: "CHAT_BUSY",
              message: "Chat is busy; no work was queued.",
            });
        if (!exactBusy) return true;
        return (
          unexpectedConsole(
            [
              {
                url: entry.url,
                text: "Failed to load resource: the server responded with a status of 429 (Too Many Requests)",
              },
            ],
            [
              entry.fact,
              ...metadataResponses.filter(
                (next) => next.order > entry.fact.order && next.status === 200,
              ),
            ],
            "http://127.0.0.1:5175",
          ).length !== 0
        );
      });
      const remainingConsole = unexpectedConsole(
        consoleErrors,
        metadataResponses,
        "http://127.0.0.1:5175",
      );
      if (!expectUnconfiguredStorage) {
        expect(remainingResponses).toEqual([]);
        expect(remainingConsole).toEqual([]);
        return;
      }
      // This suite provisions no PG/evidence workspace. Account for each exact
      // unavailable response and console record; never ignore arbitrary 503s.
      const expected: Record<string, { code: string; message: string }> = {
        "/api/v1/offline-runs": {
          code: "RUN_DB_NOT_CONFIGURED",
          message: "Offline run storage is not configured.",
        },
        "/api/v1/evidence": {
          code: "RUN_DB_NOT_CONFIGURED",
          message: "Offline run storage is not configured.",
        },
      };
      expect(
        new Set(remainingResponses.map((entry) => new URL(entry.url).pathname)),
      ).toEqual(new Set(Object.keys(expected)));
      for (const entry of remainingResponses) {
        const url = new URL(entry.url);
        expect(url.origin).toBe("http://127.0.0.1:5175");
        expect(entry.status).toBe(503);
        expect(entry.body).toEqual(expected[url.pathname]);
      }
      expect(remainingConsole.map((entry) => entry.url).sort()).toEqual(
        remainingResponses.map((entry) => entry.url).sort(),
      );
      for (const entry of remainingConsole)
        expect(entry.text).toBe(
          "Failed to load resource: the server responded with a status of 503 (Service Unavailable)",
        );
    },
  };
}
async function assertUnavailableStorage(page: Page, id: string) {
  if (id === "runs")
    await expect(
      page.getByText(
        /Offline run storage is not configured\.|OFFLINE 실행 저장소가 구성되지 않았습니다\./,
      ),
    ).toBeVisible();
  if (id === "evidence") {
    const unavailable = page.getByRole("alert").filter({
      hasText:
        /The operation could not be validated or storage is unavailable\.|작업을 검증할 수 없거나 저장소를 사용할 수 없습니다\./,
    });
    // Both the completed-Run selector and evidence repository need the absent PG.
    await expect(unavailable).toHaveCount(2);
    await expect(unavailable.nth(0)).toBeVisible();
    await expect(unavailable.nth(1)).toBeVisible();
  }
}
async function assertNoDocumentOverflow(page: Page) {
  const geometry = await page.evaluate(() => ({
    width: innerWidth,
    document: document.documentElement.scrollWidth,
  }));
  expect(geometry.document).toBeLessThanOrEqual(geometry.width + 1);
}
async function navigate(page: Page, id: string) {
  const metadataReady = id === "agent" ? waitForChatMetadata(page) : null;
  const menu = page.getByRole("button", {
    name: "Open navigation",
    exact: true,
  });
  if (await menu.isVisible()) await menu.click();
  await page.getByRole("navigation").locator(`a[href="/${id}"]`).click();
  await expect(page).toHaveURL(new RegExp("/" + id + "$"));
  await expect(page.getByRole("heading", { level: 1 })).toHaveCount(1);
  if (metadataReady) await metadataReady;
  await assertUnavailableStorage(page, id);
}
function waitForChatMetadata(page: Page) {
  return page.waitForResponse(
    (response) =>
      response.url() === "http://127.0.0.1:5175/api/v1/chat/runtime" &&
      response.request().method() === "GET" &&
      response.status() === 200,
  );
}
async function shot(page: Page, info: TestInfo, name: string) {
  await page.screenshot({
    path: info.outputPath(name + ".png"),
    fullPage: true,
  });
}

test("all 15 actual menu routes render from the real API", async ({
  page,
}, info) => {
  const observed = diagnostics(page, true);
  await page.goto("/overview");
  await expect(
    page.getByRole("heading", { name: "Validation workspace" }),
  ).toBeVisible();
  expect(navigation).toHaveLength(15);
  await shot(page, info, "overview-en-1440");
  for (const route of navigation) {
    await navigate(page, route.id);
    await expect(
      page.getByRole("navigation").locator(`a[href="/${route.id}"]`),
    ).toHaveAttribute("aria-current", "page");
    await assertNoDocumentOverflow(page);
  }
  await observed.assertHealthy();
  expect(
    observed.requests.filter(
      (url) => !url.startsWith("http://127.0.0.1:5175/"),
    ),
  ).toEqual([]);
});

test("Korean language persists and every page remains accessible", async ({
  page,
}, info) => {
  const observed = diagnostics(page, true);
  await page.goto("/overview");
  await page
    .getByRole("combobox", { name: "Interface language" })
    .selectOption("ko");
  await expect(
    page.getByRole("heading", { name: "검증 워크스페이스" }),
  ).toBeVisible();
  await page.reload();
  await expect(page.getByRole("combobox", { name: "화면 언어" })).toHaveValue(
    "ko",
  );
  await expect(page.locator("html")).toHaveAttribute("lang", "ko");
  for (const route of navigation) {
    const metadataReady = route.id === "agent" ? waitForChatMetadata(page) : null;
    await page
      .getByRole("navigation")
      .locator(`a[href="/${route.id}"]`)
      .click();
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    if (metadataReady) await metadataReady;
    await assertUnavailableStorage(page, route.id);
    await assertNoDocumentOverflow(page);
  }
  await page.goto("/overview");
  await expect(
    page.getByRole("heading", { name: "검증 워크스페이스" }),
  ).toBeVisible();
  await shot(page, info, "overview-ko-1440");
  await observed.assertHealthy();
});

for (const width of [1024, 390]) {
  test(`all pages reflow without document overflow at ${width}px`, async ({
    page,
  }, info) => {
    const observed = diagnostics(page, true);
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/overview");
    await expect(
      page.getByRole("heading", { name: "Validation workspace" }),
    ).toBeVisible();
    for (const route of navigation) {
      await navigate(page, route.id);
      await assertNoDocumentOverflow(page);
    }
    await navigate(page, "overview");
    await shot(page, info, `overview-en-${width}`);
    await navigate(page, "agent");
    await shot(page, info, `agent-en-${width}`);
    await observed.assertHealthy();
  });
}

test("keyboard page search focuses input and navigates; native dialogs restore focus", async ({
  page,
}) => {
  const observed = diagnostics(page);
  await page.goto("/overview");
  await expect(
    page.getByRole("heading", { name: "Validation workspace" }),
  ).toBeVisible();
  const trigger = page.getByRole("button", {
    name: "Search workspace",
    exact: true,
  });
  await trigger.focus();
  await page.keyboard.press("Control+k");
  const input = page.getByRole("textbox", { name: "Find a page" });
  await expect(input).toBeFocused();
  await page.keyboard.type("Skill");
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/skills$/);
  await trigger.click();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(trigger).toBeFocused();
  await navigate(page, "targets");
  const add = page.getByRole("button", { name: "Add target", exact: true });
  await add.click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(add).toBeFocused();
  await observed.assertHealthy();
});

test("real target, MCP, Skill, assignment, context and campaign drafts persist without execution", async ({
  page,
  request,
}, info) => {
  const observed = diagnostics(page);
  const targetName = "Browser target <draft>";
  const serverName = "Browser MCP";
  const skillName = "Browser Skill";
  const skillInstructions =
    "UI acceptance only. Inspect evidence before a verdict. <script>window.__ui_xss=1</script>";
  await page.goto("/targets");
  await page.getByRole("button", { name: "Add target", exact: true }).click();
  let dialog = page.getByRole("dialog");
  await dialog
    .getByRole("textbox", { name: "Name", exact: true })
    .fill(targetName);
  await dialog
    .getByRole("textbox", { name: "IP address or hostname", exact: true })
    .fill("192.0.2.10");
  await dialog.getByRole("button", { name: "Save draft", exact: true }).click();
  await expect(dialog).toHaveCount(0);
  await expect(page.getByText(targetName, { exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByText(targetName, { exact: true })).toBeVisible();

  await navigate(page, "mcp-servers");
  await page
    .getByRole("button", { name: "Add MCP server", exact: true })
    .click();
  dialog = page.getByRole("dialog");
  await dialog
    .getByRole("textbox", { name: "Name", exact: true })
    .fill(serverName);
  await dialog
    .getByRole("textbox", { name: "HTTP(S) endpoint", exact: true })
    .fill("http://127.0.0.1:59999/mcp");
  await dialog
    .getByRole("textbox", { name: "AI usage instructions", exact: true })
    .fill(
      "UI acceptance only. Use the declared measurement procedure and collect source evidence.",
    );
  await dialog.getByRole("button", { name: "Save draft", exact: true }).click();
  await expect(dialog).toHaveCount(0);
  await expect(page.getByText(serverName, { exact: true })).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Connect", exact: true }),
  ).toBeDisabled();

  await navigate(page, "skills");
  const skillForm = page.getByRole("form", { name: "Custom Skill draft" });
  await skillForm
    .getByRole("textbox", { name: "Skill name", exact: true })
    .fill(skillName);
  await skillForm
    .getByRole("textbox", { name: "Description", exact: true })
    .fill("A test-only instruction draft created by browser acceptance.");
  await skillForm
    .getByRole("textbox", { name: "Instructions", exact: true })
    .fill(skillInstructions);
  await skillForm
    .getByRole("button", { name: "Save Skill draft", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: skillName, exact: true }),
  ).toBeVisible();

  await navigate(page, "agent");
  await page.locator("details.chat-assignment > summary").click();
  await page
    .getByRole("checkbox", { name: `Assign ${skillName}`, exact: true })
    .check();
  await page
    .getByRole("checkbox", {
      name: "Assign Policy validation planning",
      exact: true,
    })
    .check();
  await page
    .getByRole("checkbox", { name: `Assign ${serverName}`, exact: true })
    .check();
  await page
    .getByRole("button", { name: "Save assignment", exact: true })
    .click();
  await expect(
    page.getByText(
      "Assignment saved as a draft. This is not operational approval.",
      { exact: true },
    ),
  ).toBeVisible();
  await page
    .getByRole("textbox", { name: "Review goal", exact: true })
    .fill("Review the draft setup; do not run a test.");
  const previewResponse = page.waitForResponse("**/api/v1/agent/preview");
  await page
    .getByRole("button", { name: "Assemble context preview", exact: true })
    .click();
  const preview = (await (await previewResponse).json()) as ContextPreview;
  expect(preview.origin).toBe("deterministic_context_preview");
  expect(preview.execution_enabled).toBe(false);
  await expect(
    page.getByRole("region", { name: "Assembled instructions" }),
  ).toContainText(skillInstructions);
  expect(await page.evaluate(() => Reflect.has(window, "__ui_xss"))).toBe(
    false,
  );
  await shot(page, info, "agent-with-real-drafts-1440");
  const metadataReload = waitForChatMetadata(page);
  await page.reload();
  await metadataReload;
  await page.locator("details.chat-assignment > summary").click();
  await expect(
    page.getByRole("checkbox", { name: `Assign ${skillName}`, exact: true }),
  ).toBeChecked();
  await expect(
    page.getByRole("checkbox", { name: `Assign ${serverName}`, exact: true }),
  ).toBeChecked();

  const before = (await (
    await request.get("/api/v1/workspace")
  ).json()) as WorkspaceSnapshot;
  const target = before.targets.find((item) => item.name === targetName);
  expect(target).toBeDefined();
  await navigate(page, "campaigns");
  await page.getByRole("button", { name: "New campaign", exact: true }).click();
  dialog = page.getByRole("dialog");
  await dialog
    .getByRole("textbox", { name: "Campaign name", exact: true })
    .fill("Browser campaign");
  await dialog
    .getByRole("textbox", { name: "Objective", exact: true })
    .fill("Verify the UI draft flow. No traffic is authorized.");
  await dialog
    .getByRole("combobox", { name: "Target", exact: true })
    .selectOption(target!.id);
  await dialog
    .getByRole("combobox", { name: "Profile template", exact: true })
    .selectOption("tcpreplay-policy");
  await dialog.getByRole("button", { name: "Save draft", exact: true }).click();
  await expect(dialog).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Browser campaign", exact: true }),
  ).toBeVisible();
  await page.reload();
  await expect(
    page.getByRole("button", { name: "Browser campaign", exact: true }),
  ).toBeVisible();
  const after = (await (
    await request.get("/api/v1/workspace")
  ).json()) as WorkspaceSnapshot;
  expect(after.campaigns.length).toBe(before.campaigns.length + 1);
  expect(after.agent_profile.skill_ids).toEqual(preview.skill_ids);
  expect(after.agent_profile.mcp_server_ids).toEqual(preview.mcp_server_ids);
  for (const key of ["runs", "findings", "evidence", "approvals"] as const)
    expect(after[key]).toEqual([]);
  expect(after.meta.live_enabled).toBe(false);
  expect(after.audit.map((event) => event.action)).toEqual(
    expect.arrayContaining([
      "target.created",
      "mcp_server.created",
      "skill.created",
      "agent_profile.updated",
      "campaign.created",
    ]),
  );
  await page.setViewportSize({ width: 390, height: 900 });
  await assertNoDocumentOverflow(page);
  await shot(page, info, "campaign-draft-390");
  await observed.assertHealthy();
  expect(observed.requests.some((url) => url.includes(":59999"))).toBe(false);
});

test("LIVE and agent execution are denied by the actual server", async ({
  request,
}) => {
  for (const [path, code] of [
    ["runs", "LIVE_NOT_AVAILABLE"],
    ["agent/execute", "AGENT_EXECUTION_NOT_AVAILABLE"],
  ]) {
    const response = await request.post("/api/v1/" + path, { data: {} });
    expect(response.status()).toBe(409);
    expect(await response.json()).toMatchObject({ code });
  }
});

test("API outage exposes retry and never substitutes fixture data", async ({
  page,
}) => {
  const runtimeErrors: string[] = [];
  page.on("pageerror", (error) => runtimeErrors.push(error.message));
  await page.route("**/api/v1/workspace", (route) =>
    route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({
        code: "TEST_OUTAGE",
        message: "Injected test-only outage",
      }),
    }),
  );
  await page.goto("/overview");
  await expect(
    page.getByRole("heading", { name: "Local API is unavailable" }),
  ).toBeVisible();
  await expect(page.getByTestId("target-count")).toHaveCount(0);
  await page.unroute("**/api/v1/workspace");
  await page
    .getByRole("button", { name: "Retry connection", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Validation workspace" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Local API is unavailable" }),
  ).toHaveCount(0);
  expect(runtimeErrors).toEqual([]);
});

test("deep links, history and unknown routes behave deliberately", async ({
  page,
}) => {
  const observed = diagnostics(page);
  await page.goto("/skills");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await navigate(page, "targets");
  await page.goBack();
  await expect(page).toHaveURL(/\/skills$/);
  await expect(
    page.getByRole("navigation").locator('a[href="/skills"]'),
  ).toHaveAttribute("aria-current", "page");
  await page.goto("/not-a-real-page");
  await expect(
    page.getByRole("heading", { name: "Page not found" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Back to overview" }).click();
  await expect(
    page.getByRole("heading", { name: "Validation workspace" }),
  ).toBeVisible();
  await observed.assertHealthy();
});

test("representative real pages pass automated accessibility checks", async ({
  page,
}, info) => {
  for (const route of ["overview", "targets", "skills", "agent", "campaigns"]) {
    await page.goto("/" + route);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    const result = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
      .analyze();
    await info.attach("axe-" + route, {
      body: JSON.stringify(result.violations, null, 2),
      contentType: "application/json",
    });
    expect(result.violations, route).toEqual([]);
  }
});
