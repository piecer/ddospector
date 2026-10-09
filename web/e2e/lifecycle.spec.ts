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
    field: "IP address or hostname",
    value: "192.0.2.51",
    key: "targets",
    table: "Target drafts",
  },
  {
    route: "mcp-servers",
    add: "Add MCP server",
    field: "HTTP(S) endpoint",
    value: "http://127.0.0.1:59999/mcp",
    key: "mcp_servers",
    table: "MCP server drafts",
  },
] as const;
type Draft = (typeof drafts)[number];

async function tabTo(page: Page, control: Locator) {
  for (let i = 0; i < 12; i++) {
    await page.keyboard.press("Tab");
    if (await control.evaluate((node) => node === document.activeElement))
      return;
  }
  await expect(control).toBeFocused();
}

async function prepare(
  page: Page,
  request: APIRequestContext,
  info: TestInfo,
  item: Draft,
) {
  const name = `Lifecycle ${info.title}`;
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
  const add = page.getByRole("button", { name: item.add, exact: true });
  await add.click();
  // Unchanged native dismissal, then keyboard reopening from the same invoker.
  await page.keyboard.press("Escape");
  await expect(add).toBeFocused();
  await page.keyboard.press("Enter");
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("textbox", { name: "Name", exact: true }).fill(name);
  await dialog
    .getByRole("textbox", { name: item.field, exact: true })
    .fill(item.value);
  if (item.route === "mcp-servers")
    await dialog
      .getByRole("textbox", { name: "AI usage instructions", exact: true })
      .fill("Local metadata only; never connect to an endpoint.");

  const held: Route[] = [];
  // Only hold GET delivery: the POST and every successful read use the real API.
  await page.route("**/api/v1/workspace", (route) => {
    expect(route.request().method()).toBe("GET");
    held.push(route);
  });
  const response = page.waitForResponse(
    (res) =>
      res.request().method() === "POST" &&
      res.url().endsWith("/api/v1/" + item.route),
  );
  await dialog.getByRole("button", { name: "Save draft", exact: true }).click();
  const posted = await response;
  expect(posted.ok()).toBe(true);
  const created = await posted.json();
  await expect.poll(() => held.length).toBe(1);
  await expect(page.locator("body > dialog:modal")).toHaveCount(1);
  await expect(add).toBeDisabled();
  for (const field of await dialog.locator("input,select,textarea").all())
    await expect(field).toBeDisabled();

  async function settle(index: number, success: boolean) {
    await expect.poll(() => held.length).toBe(index + 1);
    if (success) {
      const response = await held[index].fetch();
      expect(response.ok()).toBe(true);
      await held[index].fulfill({ response });
    } else {
      await held[index].fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({
          code: "TEST_READBACK_OUTAGE",
          message: "Injected GET failure",
        }),
      });
    }
  }
  const retry = dialog.getByRole("button", {
    name: "Retry refresh",
    exact: true,
  });
  async function repeatedFailures() {
    for (let index = 0; index < 3; index++) {
      if (index) {
        if (index === 1) await retry.click();
        else {
          await tabTo(page, retry);
          await page.keyboard.press("Enter");
        }
      }
      await settle(index, false);
      await expect(retry).toBeEnabled();
      await expect(
        dialog.getByRole("button", { name: "Close", exact: true }),
      ).toBeEnabled();
      await expect(
        dialog.getByRole("button", { name: "Close dialog", exact: true }),
      ).toBeEnabled();
      await expect(add).toBeDisabled();
      for (const field of await dialog.locator("input,select,textarea").all())
        await expect(field).toBeDisabled();
    }
  }
  async function persisted() {
    const response = await request.get("/api/v1/workspace");
    expect(response.ok()).toBe(true);
    const data = await response.json();
    const records = data[item.key].filter(
      (record: { name: string }) => record.name === name,
    );
    await info.attach("lifecycle-record-and-requests", {
      body: JSON.stringify(
        { created, records, mutations, external, errors, reads: held.length },
        null,
        2,
      ),
      contentType: "application/json",
    });
    expect(records).toEqual([created]);
    expect(mutations).toEqual(["POST /api/v1/" + item.route]);
    expect(external).toEqual([]);
    expect(errors).toEqual([]);
  }
  return {
    name,
    add,
    dialog,
    retry,
    settle,
    held,
    repeatedFailures,
    persisted,
  };
}

for (const item of drafts) {
  for (const recovery of [false, true]) {
    test(`${item.route}: ${recovery ? "repeated failed GET then retry" : "normal successful save"} restores original Add focus`, async ({
      page,
      request,
    }, info) => {
      const saved = await prepare(page, request, info, item);
      if (recovery) {
        await saved.repeatedFailures();
        await tabTo(page, saved.retry);
        await page.keyboard.press("Enter");
      }
      await saved.settle(recovery ? 3 : 0, true);
      await expect(saved.dialog).toHaveCount(0);
      await expect(page.locator("dialog[open], dialog:modal")).toHaveCount(0);
      await expect(saved.add).toBeEnabled();
      await expect(page.getByText(saved.name, { exact: true })).toBeVisible();
      await saved.persisted();
      await info.attach("focus-after-save", {
        body: await page.evaluate(
          () => document.activeElement?.outerHTML ?? "none",
        ),
        contentType: "text/plain",
      });
      // UI01-FE-003: both real callers must fail here before the Dialog correction.
      await expect(
        saved.add,
        "successful readback restores the original Add invoker",
      ).toBeFocused();
      await page.keyboard.press("Tab");
      await expect(
        page.getByRole("region", { name: item.table, exact: true }),
      ).toBeFocused();
      await page.unroute("**/api/v1/workspace");
      await page.reload();
      await expect(page.getByText(saved.name, { exact: true })).toBeVisible();
      await saved.persisted();
    });
  }

  for (const control of ["Close", "Close dialog"]) {
    for (const input of ["pointer", "keyboard"]) {
      for (const settlement of [
        "failed",
        "pending failure",
        "pending success",
      ]) {
        test(`${item.route}: ${control} ${input} after repeated errors, ${settlement}`, async ({
          page,
          request,
        }, info) => {
          const saved = await prepare(page, request, info, item);
          await saved.repeatedFailures();
          if (settlement !== "failed") {
            await saved.retry.click();
            await expect.poll(() => saved.held.length).toBe(4);
            await expect(
              saved.dialog.getByRole("button", {
                name: "Saving…",
                exact: true,
              }),
            ).toBeDisabled();
          }
          const close = saved.dialog.getByRole("button", {
            name: control,
            exact: true,
          });
          await expect(close).toBeEnabled();
          if (input === "pointer") await close.click();
          else {
            await tabTo(page, close);
            await page.keyboard.press("Enter");
          }
          await expect(saved.dialog).toHaveCount(0);
          await expect(saved.add).toBeDisabled();
          await expect(saved.add).not.toBeFocused();

          // New work in a nonportal Dialog must keep focus when the old save settles.
          const search = page.getByRole("button", {
            name: "Search workspace",
            exact: true,
          });
          await search.click();
          const query = page.getByRole("textbox", {
            name: "Find a page",
            exact: true,
          });
          await query.fill("Skill");
          if (settlement !== "failed") {
            await saved.settle(3, settlement === "pending success");
            if (settlement === "pending success")
              await expect(saved.add).toBeEnabled();
            else
              await expect(
                page.locator(".connection-error-panel"),
              ).toBeVisible();
          }
          await expect(query).toHaveValue("Skill");
          await expect(query).toBeFocused();
          await expect(page.locator("dialog:modal")).toHaveCount(1);
          await expect(
            page.getByRole("dialog", { name: /Add .* draft/ }),
          ).toHaveCount(0);
          await page.keyboard.press("Escape");
          await expect(search).toBeFocused();
          await expect(page.locator("dialog:modal")).toHaveCount(0);
          if (settlement !== "pending success") {
            await expect(saved.add).toBeDisabled();
            await page.unroute("**/api/v1/workspace");
            const reconnect = page.getByRole("button", {
              name: "Retry connection",
              exact: true,
            });
            await reconnect.click();
            await expect(saved.add).toBeEnabled();
            await expect(saved.add).not.toBeFocused();
          }
          await expect(
            page.getByText(saved.name, { exact: true }),
          ).toBeVisible();
          await saved.persisted();
        });
      }
    }
  }
}
