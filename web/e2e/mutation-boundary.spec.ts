import { expect, test } from "@playwright/test";
import type { Route } from "@playwright/test";

test("an older save readback cannot unlock a still-open unrelated campaign draft", async ({
  page,
  request,
}) => {
  const seed = await request.post("/api/v1/targets", {
    data: { name: "Boundary prerequisite", address: "192.0.2.30", kind: "DUT" },
  });
  expect(seed.ok()).toBe(true);
  const target = await seed.json();
  const workspace = await (await request.get("/api/v1/workspace")).json();
  const mutations: string[] = [];
  const external: string[] = [];
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
  await page.goto("/targets");
  await page.getByRole("button", { name: "Add target", exact: true }).click();
  let dialog = page.getByRole("dialog");
  await dialog
    .getByRole("textbox", { name: "Name", exact: true })
    .fill("Boundary delayed target");
  await dialog
    .getByRole("textbox", { name: "IP address or hostname", exact: true })
    .fill("192.0.2.31");
  let releasePost!: () => void;
  const postHeld = new Promise<void>((resolve) => {
    releasePost = resolve;
  });
  let posted = false;
  await page.route("**/api/v1/targets", async (route) => {
    const response = await route.fetch();
    expect(response.ok()).toBe(true);
    posted = true;
    await postHeld;
    await route.fulfill({ response });
  });
  await dialog.getByRole("button", { name: "Save draft", exact: true }).click();
  await expect.poll(() => posted).toBe(true);
  await dialog.getByRole("button", { name: "Close", exact: true }).click();
  await page.getByRole("navigation").locator('a[href="/campaigns"]').click();
  await page.getByRole("button", { name: "New campaign", exact: true }).click();
  dialog = page.getByRole("dialog");
  const name = dialog.getByRole("textbox", {
    name: "Campaign name",
    exact: true,
  });
  await name.fill("Unsaved sibling campaign");
  await dialog
    .getByRole("textbox", { name: "Objective", exact: true })
    .fill("Must stay unsaved during another page's readback outage.");
  await dialog
    .getByRole("combobox", { name: "Target", exact: true })
    .selectOption(target.id);
  await dialog
    .getByRole("combobox", { name: "Profile template", exact: true })
    .selectOption(workspace.profiles[0].id);
  const save = dialog.getByRole("button", { name: "Save draft", exact: true });
  await expect(save).toBeEnabled();
  let pendingRead: Route | undefined;
  await page.route("**/api/v1/workspace", (route) => {
    pendingRead = route;
  });
  // The old page's real POST completes only once this unrelated valid draft is open.
  releasePost();
  await expect.poll(() => Boolean(pendingRead)).toBe(true);
  await expect(name).toBeDisabled();
  await expect(save).toBeDisabled();
  await page.keyboard.press("Enter");
  expect(mutations).toEqual(["POST /api/v1/targets"]);
  await pendingRead!.fulfill({
    status: 503,
    contentType: "application/json",
    body: JSON.stringify({
      code: "TEST_READBACK_OUTAGE",
      message: "Readback failed",
    }),
  });
  await expect(page.locator(".connection-error-panel")).toContainText(
    "Local API is unavailable",
  );
  await expect(name).toBeDisabled();
  await expect(save).toBeDisabled();
  await page.keyboard.press("Enter");
  expect(mutations).toEqual(["POST /api/v1/targets"]);
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await page.getByRole("navigation").locator('a[href="/agent"]').click();
  await page.locator("details.chat-assignment > summary").click();
  await expect(
    page.getByRole("button", { name: "Save assignment", exact: true }),
  ).toBeDisabled();
  for (const checkbox of await page.getByRole("checkbox").all())
    await expect(checkbox).toBeDisabled();
  expect(mutations).toEqual(["POST /api/v1/targets"]);
  await page.unroute("**/api/v1/workspace");
  await page
    .getByRole("button", { name: "Retry connection", exact: true })
    .click();
  await expect(page.locator(".connection-error-panel")).toHaveCount(0);
  const after = await (await request.get("/api/v1/workspace")).json();
  expect(
    after.targets.filter(
      (entry: { name: string }) => entry.name === "Boundary delayed target",
    ),
  ).toHaveLength(1);
  expect(after.campaigns).toEqual(workspace.campaigns);
  expect(after.agent_profile).toEqual(workspace.agent_profile);
  expect(mutations).toEqual(["POST /api/v1/targets"]);
  expect(external).toEqual([]);
});
