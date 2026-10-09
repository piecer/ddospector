import { expect, test } from "@playwright/test";
import type {
  APIRequestContext,
  Locator,
  Page,
  Route,
  TestInfo,
} from "@playwright/test";

const drafts = [
  {
    route: "targets",
    add: "Add target",
    address: "IP address or hostname",
    value: "192.0.2.20",
    key: "targets",
  },
  {
    route: "mcp-servers",
    add: "Add MCP server",
    address: "HTTP(S) endpoint",
    value: "http://127.0.0.1:59999/mcp",
    key: "mcp_servers",
  },
] as const;
type Draft = (typeof drafts)[number];

async function tabTo(page: Page, control: Locator) {
  // Prove actual sequential keyboard access, not just programmatic focus.
  for (let attempt = 0; attempt < 12; attempt++) {
    await page.keyboard.press("Tab");
    if (await control.evaluate((node) => node === document.activeElement))
      return;
  }
  await expect(control).toBeFocused();
}

async function savedDuringOutage(
  page: Page,
  request: APIRequestContext,
  item: Draft,
  info: TestInfo,
) {
  const name = `Readback ${item.route} ${info.title}`;
  const mutations: string[] = [];
  const external: string[] = [];
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("request", (req) => {
    if (["POST", "PUT", "PATCH", "DELETE"].includes(req.method()))
      mutations.push(`${req.method()} ${new URL(req.url()).pathname}`);
  });
  await page.route("**/*", async (route) => {
    if (new URL(route.request().url()).origin !== "http://127.0.0.1:5175") {
      external.push(route.request().url());
      await route.abort();
    } else await route.continue();
  });
  await page.goto("/" + item.route);
  await page.getByRole("button", { name: item.add, exact: true }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("textbox", { name: "Name", exact: true }).fill(name);
  await dialog
    .getByRole("textbox", { name: item.address, exact: true })
    .fill(item.value);
  if (item.route === "mcp-servers") {
    await dialog
      .getByRole("textbox", { name: "AI usage instructions", exact: true })
      .fill(
        "Local metadata only. Never contact an endpoint or execute a tool.",
      );
  }
  let reads = 0;
  let pending: Route | undefined;
  let hold = false;
  const fail = (route: Route) =>
    route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({
        code: "TEST_READBACK_OUTAGE",
        message: "Injected workspace read failure",
      }),
    });
  // Only readback is injected. The create is a real POST to the isolated API.
  await page.route("**/api/v1/workspace", async (route) => {
    expect(route.request().method()).toBe("GET");
    reads++;
    if (hold) pending = route;
    else await fail(route);
  });
  const response = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      response.url().endsWith("/api/v1/" + item.route),
  );
  await dialog.getByRole("button", { name: "Save draft", exact: true }).click();
  const createdResponse = await response;
  expect(createdResponse.ok()).toBe(true);
  const created = await createdResponse.json();
  const warning = dialog.getByText(
    "Draft saved, but the workspace could not refresh. Retry refresh without creating another draft.",
    { exact: true },
  );
  await expect(warning).toBeVisible();

  async function assertPersisted() {
    const readback = await request.get("/api/v1/workspace");
    expect(readback.ok()).toBe(true);
    const data = await readback.json();
    const copies = data[item.key].filter(
      (record: { name: string }) => record.name === name,
    );
    expect(copies).toHaveLength(1);
    expect(copies[0]).toEqual(created);
    expect(mutations).toEqual(["POST /api/v1/" + item.route]);
    expect(external).toEqual([]);
    expect(errors).toEqual([]);
    await info.attach("durable-record-and-requests", {
      body: JSON.stringify(
        { created, copies, mutations, reads, external, errors },
        null,
        2,
      ),
      contentType: "application/json",
    });
  }
  // This runs even on the predecessor before the intended accessibility RED.
  await assertPersisted();
  return {
    name,
    dialog,
    warning,
    assertPersisted,
    readCount: () => reads,
    holdNextRead: () => {
      hold = true;
    },
    failHeldRead: async () => {
      expect(pending).toBeDefined();
      await fail(pending!);
      hold = false;
    },
    restore: () => page.unroute("**/api/v1/workspace"),
  };
}

for (const item of drafts) {
  test(`${item.route}: pointer and keyboard recovery survives repeated read failure`, async ({
    page,
    request,
  }, info) => {
    const saved = await savedDuringOutage(page, request, item, info);
    const retry = saved.dialog.getByRole("button", {
      name: "Retry refresh",
      exact: true,
    });
    const footerClose = saved.dialog.getByRole("button", {
      name: "Close",
      exact: true,
    });
    const headerClose = saved.dialog.getByRole("button", {
      name: "Close dialog",
      exact: true,
    });
    await expect(retry).toBeEnabled({ timeout: 1500 });
    await expect(footerClose).toBeEnabled();
    await expect(headerClose).toBeEnabled();
    await expect(
      saved.dialog.getByRole("textbox", { name: "Name", exact: true }),
    ).toBeDisabled();
    await expect(page.locator(".page-fieldset").first()).toHaveAttribute(
      "disabled",
      "",
    );
    await expect(
      page.locator(".page-fieldset button").filter({ hasText: item.add }),
    ).toBeDisabled();
    saved.holdNextRead();
    await retry.click();
    await expect.poll(saved.readCount).toBe(2);
    await expect(
      saved.dialog.getByRole("button", { name: "Saving…", exact: true }),
    ).toBeDisabled();
    await expect(footerClose).toBeEnabled();
    await expect(headerClose).toBeEnabled();
    await saved.failHeldRead();
    await expect(saved.warning).toBeVisible();
    await expect(retry).toBeEnabled();
    await saved.assertPersisted();
    await tabTo(page, retry);
    await page.keyboard.press("Enter");
    await expect.poll(saved.readCount).toBe(3);
    await expect(saved.warning).toBeVisible();
    await saved.restore();
    await tabTo(page, retry);
    await page.keyboard.press("Enter");
    await expect(saved.dialog).toHaveCount(0);
    await expect(page.getByText(saved.name, { exact: true })).toBeVisible();
    await page.reload();
    await expect(page.getByText(saved.name, { exact: true })).toBeVisible();
    await saved.assertPersisted();
  });

  for (const control of ["Close", "Close dialog"] as const) {
    for (const input of ["pointer", "keyboard"] as const) {
      test(`${item.route}: ${control} dismissal by ${input} preserves one create`, async ({
        page,
        request,
      }, info) => {
        const saved = await savedDuringOutage(page, request, item, info);
        const close = saved.dialog.getByRole("button", {
          name: control,
          exact: true,
        });
        await expect(close).toBeEnabled({ timeout: 1500 });
        if (input === "pointer") await close.click();
        else {
          await tabTo(page, close);
          await page.keyboard.press("Enter");
        }
        await expect(saved.dialog).toHaveCount(0);
        // Dismissal must not re-enable mutations against the stale snapshot.
        await expect(
          page.getByRole("button", { name: item.add, exact: true }),
        ).toBeDisabled();
        const globalRetry = page.getByRole("button", {
          name: "Retry connection",
          exact: true,
        });
        await globalRetry.click();
        await expect.poll(saved.readCount).toBe(2);
        await expect(globalRetry).toBeVisible();
        await expect(
          page.getByRole("button", { name: item.add, exact: true }),
        ).toBeDisabled();
        await saved.restore();
        await globalRetry.click();
        await expect(page.getByText(saved.name, { exact: true })).toBeVisible();
        await expect(
          page.getByRole("button", { name: item.add, exact: true }),
        ).toBeEnabled();
        await page.reload();
        await expect(page.getByText(saved.name, { exact: true })).toBeVisible();
        await saved.assertPersisted();
      });
    }
  }
}
