import { expect, test } from "@playwright/test";

test("documented root enters overview and preserves history, localization and unknown routes", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await expect(
    page.getByRole("heading", { level: 1, name: "Validation workspace" }),
  ).toBeVisible({ timeout: 1500 });
  await expect(
    page.getByRole("navigation").locator('a[href="/overview"]'),
  ).toHaveAttribute("aria-current", "page");
  await expect(page).toHaveTitle("Overview · DDoSpector");
  await page.getByRole("navigation").locator('a[href="/targets"]').click();
  await expect(page).toHaveURL(/\/targets$/);
  await page.goBack();
  await expect(page).toHaveURL("http://127.0.0.1:5175/");
  await expect(
    page.getByRole("heading", { name: "Validation workspace" }),
  ).toBeVisible();
  await page.goForward();
  await expect(page).toHaveURL(/\/targets$/);
  await page.goBack();
  await page
    .getByRole("combobox", { name: "Interface language" })
    .selectOption("ko");
  await expect(
    page.getByRole("heading", { name: "검증 워크스페이스" }),
  ).toBeVisible();
  await expect(page).toHaveTitle("워크스페이스 · DDoSpector");
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("lang", "ko");
  await expect(
    page.getByRole("heading", { name: "검증 워크스페이스" }),
  ).toBeVisible();
  await page.goto("/genuinely-unknown-page");
  await expect(
    page.getByRole("heading", { name: "페이지를 찾을 수 없습니다" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "개요로 돌아가기" }).click();
  await expect(page).toHaveURL(/\/overview$/);
  await expect(
    page.getByRole("heading", { name: "검증 워크스페이스" }),
  ).toBeVisible();
  expect(errors).toEqual([]);
});
