import { randomUUID } from "node:crypto";
import {
  expect,
  test,
  type Page,
  type APIRequestContext,
} from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import type { AISettingsSnapshot } from "../src/pages/ai-settings/types";

const endpoint = "/api/v1/ai-settings";
const en = {
  title: "AI settings",
  create: "Create profile",
  name: "Profile name",
  model: "Model ID",
  save: "Save profile",
  close: "Close",
  advanced: "Advanced settings",
  retry: "Retry policy",
  protocol: "Protocol",
  outputField: "Output token field",
  thinking: "Thinking",
  effort: "Reasoning effort",
  default: "Default draft",
  agent: "Review-agent draft",
  bindings: "Save bindings",
  edit: "Edit ",
  remove: "Delete ",
  confirm: "Delete profile",
  rate: "Requests per second",
};
const ko = {
  title: "AI 설정",
  create: "프로필 만들기",
  name: "프로필 이름",
  model: "모델 ID",
  save: "프로필 저장",
  close: "닫기",
  advanced: "고급 설정",
  retry: "재시도 정책",
  protocol: "프로토콜",
  outputField: "출력 토큰 필드",
  thinking: "사고 모드",
  effort: "추론 강도",
  default: "기본 초안",
  agent: "검토 에이전트 초안",
  bindings: "바인딩 저장",
  edit: "편집 ",
  remove: "삭제 ",
  confirm: "프로필 삭제",
  rate: "초당 요청 수",
};
async function snapshot(
  request: APIRequestContext,
): Promise<AISettingsSnapshot> {
  const response = await request.get(endpoint);
  expect(response.status()).toBe(200);
  return response.json();
}
async function restore(
  request: APIRequestContext,
  original: AISettingsSnapshot,
) {
  const current = await snapshot(request);
  const response = await request.put(endpoint, {
    data: {
      revision: current.revision,
      profiles: original.profiles,
      default_profile_id: original.default_profile_id,
      agent_profile_id: original.agent_profile_id,
    },
  });
  expect(response.status()).toBe(200);
  const saved = await response.json();
  expect(await snapshot(request)).toEqual(saved);
}
async function open(page: Page, locale: "en" | "ko" = "en") {
  await page.goto("/ai-settings");
  if (locale === "ko")
    await page
      .getByRole("combobox", { name: "Interface language", exact: true })
      .selectOption("ko");
  const words = locale === "ko" ? ko : en;
  await expect(
    page.getByRole("heading", { level: 1, name: words.title }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: words.create, exact: true }),
  ).toBeEnabled();
}
async function begin(page: Page, name: string, words = en) {
  await page.getByRole("button", { name: words.create, exact: true }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await dialog.getByLabel(words.name, { exact: true }).fill(name);
  await dialog
    .getByLabel(words.model, { exact: true })
    .fill("operator/literal-model:unverified");
  return dialog;
}
function nextPut(page: Page) {
  return page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === endpoint &&
      response.request().method() === "PUT",
  );
}
async function save(page: Page, label: string): Promise<AISettingsSnapshot> {
  const response = nextPut(page);
  await page.getByRole("button", { name: label, exact: true }).click();
  const receipt = await response;
  expect(receipt.status()).toBe(200);
  return receipt.json();
}
function observe(page: Page) {
  const errors: string[] = [],
    external: string[] = [];
  const methods: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (
      ["http:", "https:"].includes(url.protocol) &&
      url.origin !== "http://127.0.0.1:5175"
    )
      external.push(request.url());
    if (url.pathname === endpoint) methods.push(request.method());
  });
  return { errors, external, methods };
}
function barrier() {
  let release!: () => void;
  const promise = new Promise<void>((resolve) => {
    release = resolve;
  });
  return { promise, release };
}

for (const locale of ["en", "ko"] as const) {
  test(`real profile CRUD, all protocols, bindings, reload and authoritative receipt (${locale})`, async ({
    page,
    request,
  }, info) => {
    const original = await snapshot(request);
    const observed = observe(page);
    const words = locale === "ko" ? ko : en;
    const name = `모델-${randomUUID()}`;
    await open(page, locale);
    const dialog = await begin(page, name, words);
    await dialog.locator("summary").filter({ hasText: words.advanced }).click();
    await dialog.getByLabel(words.rate, { exact: true }).fill("17");
    await dialog
      .getByLabel(words.outputField, { exact: true })
      .selectOption("max_completion_tokens");
    await dialog
      .getByLabel(words.thinking, { exact: true })
      .selectOption("disabled");
    await dialog.getByLabel(words.effort, { exact: true }).selectOption("high");
    const readsBefore = observed.methods.filter(
      (method) => method === "GET",
    ).length;
    let saved = await save(page, words.save);
    await expect(dialog).not.toBeVisible();
    await expect(
      page.getByRole("heading", { name, exact: true }),
    ).toBeVisible();
    expect(observed.methods.filter((method) => method === "GET")).toHaveLength(
      readsBefore,
    );
    expect(saved.default_profile_id).toBe(original.default_profile_id);
    expect(saved.agent_profile_id).toBe(original.agent_profile_id);
    const profile = saved.profiles.find((value) => value.name === name)!;
    expect(profile).toMatchObject({
      format: "openai",
      rate_per_second: 17,
      thinking_type: "disabled",
      reasoning_effort: "high",
    });
    expect(await snapshot(request)).toEqual(saved);
    await page.screenshot({
      path: info.outputPath(`ai-profiles-${locale}-1440.png`),
      fullPage: true,
    });
    await page.reload();
    await expect(
      page.getByRole("heading", { name, exact: true }),
    ).toBeVisible();
    await page
      .getByRole("button", { name: words.edit + name, exact: true })
      .click();
    await dialog
      .getByLabel(words.protocol, { exact: true })
      .selectOption("openai-responses");
    await dialog.locator("summary").filter({ hasText: words.advanced }).click();
    await expect(
      dialog.getByLabel(words.outputField, { exact: true }),
    ).toBeDisabled();
    await expect(
      dialog.getByLabel(words.outputField, { exact: true }),
    ).toHaveValue("");
    await expect(dialog.getByLabel(words.rate, { exact: true })).toHaveValue(
      "17",
    );
    saved = await save(page, words.save);
    expect(
      saved.profiles.find((value) => value.id === profile.id),
    ).toMatchObject({
      format: "openai-responses",
      max_tokens_field: "",
      thinking_type: "disabled",
      reasoning_effort: "high",
    });
    await expect(dialog).not.toBeVisible();
    await page
      .getByLabel(words.default, { exact: true })
      .selectOption(profile.id);
    await page
      .getByLabel(words.agent, { exact: true })
      .selectOption(profile.id);
    saved = await save(page, words.bindings);
    expect(saved).toMatchObject({
      default_profile_id: profile.id,
      agent_profile_id: profile.id,
    });
    await expect(
      page.getByRole("button", { name: words.remove + name, exact: true }),
    ).toBeDisabled();
    await page.reload();
    await expect(page.getByLabel(words.agent, { exact: true })).toHaveValue(
      profile.id,
    );
    await page.getByLabel(words.default, { exact: true }).selectOption("");
    await page.getByLabel(words.agent, { exact: true }).selectOption("");
    await save(page, words.bindings);
    await page
      .getByRole("button", { name: words.edit + name, exact: true })
      .click();
    await dialog
      .getByLabel(words.protocol, { exact: true })
      .selectOption("anthropic");
    saved = await save(page, words.save);
    expect(
      saved.profiles.find((value) => value.id === profile.id)?.format,
    ).toBe("anthropic");
    await expect(dialog).not.toBeVisible();
    await begin(page, "unsaved-second-profile", words);
    await dialog.locator("summary").filter({ hasText: words.advanced }).click();
    await expect(dialog.getByLabel(words.rate, { exact: true })).toHaveValue(
      "0",
    );
    await dialog
      .getByRole("button", { name: words.close, exact: true })
      .click();
    await expect(
      page.getByRole("button", { name: words.create, exact: true }),
    ).toBeFocused();
    await page
      .getByRole("button", { name: words.remove + name, exact: true })
      .click();
    await expect(dialog).toBeVisible();
    saved = await save(page, words.confirm);
    await expect(dialog).not.toBeVisible();
    expect(saved.profiles).toEqual(original.profiles);
    expect(await snapshot(request)).toEqual(saved);
    const browserStorage = await page.evaluate(() => ({
      local: { ...localStorage },
      session: { ...sessionStorage },
    }));
    expect(browserStorage).toEqual({
      local: { "aegis.locale": locale },
      session: {},
    });
    expect(observed.errors).toEqual([]);
    expect(observed.external).toEqual([]);
    await restore(request, original);
  });
}

test("long text, native keyboard focus, and automated accessibility at 1440/1024/390", async ({
  page,
  request,
}, info) => {
  const original = await snapshot(request);
  const observed = observe(page);
  const name = "긴 모델 " + "가".repeat(110);
  const model = "모".repeat(200);
  const url = "https://example.invalid/" + "x".repeat(480);
  await open(page);
  const dialog = await begin(page, name);
  await dialog.getByLabel("Model ID", { exact: true }).fill(model);
  await dialog.getByLabel("Base URL", { exact: true }).fill(url);
  await save(page, "Save profile");
  await expect(dialog).not.toBeVisible();
  for (const width of [1440, 1024, 390]) {
    await page.setViewportSize({ width, height: 900 });
    await expect(page.getByText(model, { exact: true })).toBeVisible();
    await expect(page.getByText(url, { exact: true })).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth + 1,
      ),
    ).toBe(true);
    expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
    await page.screenshot({
      path: info.outputPath(`ai-long-en-${width}.png`),
      fullPage: true,
    });
    const edit = page.getByRole("button", {
      name: "Edit " + name,
      exact: true,
    });
    await edit.focus();
    await page.keyboard.press("Enter");
    await expect(dialog).toBeVisible();
    await dialog
      .locator("summary")
      .filter({ hasText: "Advanced settings" })
      .click();
    await dialog.locator("summary").filter({ hasText: "Retry policy" }).click();
    for (let index = 0; index < 24; index++) {
      await page.keyboard.press(index % 3 === 0 ? "Shift+Tab" : "Tab");
      expect(
        await dialog.evaluate((element) =>
          element.contains(document.activeElement),
        ),
      ).toBe(true);
    }
    const geometry = await dialog.boundingBox();
    expect(geometry).not.toBeNull();
    expect(geometry!.x).toBeGreaterThanOrEqual(0);
    expect(geometry!.x + geometry!.width).toBeLessThanOrEqual(width + 1);
    expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
    await page.screenshot({
      path: info.outputPath(`ai-editor-en-${width}.png`),
      fullPage: true,
    });
    await page.keyboard.press("Escape");
    await expect(dialog).not.toBeVisible();
    await expect(edit).toBeFocused();
  }
  expect(observed.errors).toEqual([]);
  expect(observed.external).toEqual([]);
  await restore(request, original);
});

for (const fault of ["conflict", "unacknowledged-commit"] as const) {
  test(`${fault} locks mutations, preserves the form, and recovers by read without replay`, async ({
    page,
    request,
  }) => {
    const original = await snapshot(request);
    const observed = observe(page);
    const name = `recover-${randomUUID()}`;
    await open(page);
    const dialog = await begin(page, name);
    if (fault === "conflict")
      await restore(request, original); // Real competing revision.
    else
      await page.route("**/api/v1/ai-settings", async (route) => {
        if (route.request().method() !== "PUT") return route.continue();
        const response = await route.fetch();
        expect(response.status()).toBe(200);
        await route.fulfill({
          status: 503,
          json: {
            code: "STATE_COMMIT_UNCERTAIN",
            message: "Injected lost acknowledgement.",
          },
        });
      });
    await dialog
      .getByRole("button", { name: "Save profile", exact: true })
      .click();
    await expect(
      dialog.getByText(/The save was not acknowledged/),
    ).toBeVisible();
    await expect(
      dialog.getByLabel("Profile name", { exact: true }),
    ).toHaveValue(name);
    await expect(
      dialog.getByRole("button", { name: "Save profile", exact: true }),
    ).toBeDisabled();
    await expect(
      dialog.getByRole("button", { name: "Close", exact: true }),
    ).toBeEnabled();
    const persisted = await snapshot(request);
    expect(persisted.profiles.some((value) => value.name === name)).toBe(
      fault === "unacknowledged-commit",
    );
    await dialog
      .getByRole("button", {
        name: "Reload saved settings (discard local edits)",
        exact: true,
      })
      .click();
    await expect(dialog).not.toBeVisible();
    await expect(
      page.getByRole("button", { name: "Create profile", exact: true }),
    ).toBeEnabled();
    await expect(
      page.getByRole("button", { name: "Create profile", exact: true }),
    ).toBeFocused();
    expect(observed.methods.filter((method) => method === "PUT")).toHaveLength(
      1,
    );
    expect(await snapshot(request)).toEqual(persisted);
    expect(observed.errors).toEqual([]);
    await page.unroute("**/api/v1/ai-settings");
    await restore(request, original);
  });
}

for (const outcome of ["success", "failure"] as const) {
  test(`closing a pending save survives late ${outcome} without focus theft or duplicate PUT`, async ({
    page,
    request,
  }) => {
    const original = await snapshot(request);
    const observed = observe(page);
    const committed = barrier(),
      released = barrier(),
      settled = barrier();
    const name = `late-${randomUUID()}`;
    await open(page);
    await page.route("**/api/v1/ai-settings", async (route) => {
      if (route.request().method() !== "PUT") return route.continue();
      const response = await route.fetch();
      expect(response.status()).toBe(200);
      committed.release();
      await released.promise;
      try {
        if (outcome === "success") await route.fulfill({ response });
        else
          await route.fulfill({
            status: 503,
            json: { code: "STATE_COMMIT_UNCERTAIN" },
          });
      } finally {
        settled.release();
      }
    });
    try {
      const dialog = await begin(page, name);
      await dialog
        .getByRole("button", { name: "Save profile", exact: true })
        .click();
      await committed.promise;
      await expect(
        dialog.getByRole("button", { name: "Save profile", exact: true }),
      ).toBeDisabled();
      await dialog.getByRole("button", { name: "Close", exact: true }).click();
      await expect(dialog).not.toBeVisible();
      const newFocus = page.getByRole("combobox", {
        name: "Interface language",
        exact: true,
      });
      await newFocus.focus();
      released.release();
      await settled.promise;
      if (outcome === "success")
        await expect(
          page.getByText("Draft settings saved. No model was contacted.", {
            exact: true,
          }),
        ).toBeVisible();
      else
        await expect(
          page.getByText(/The save was not acknowledged/),
        ).toBeVisible();
      await expect(dialog).not.toBeVisible();
      await expect(newFocus).toBeFocused();
      expect(
        observed.methods.filter((method) => method === "PUT"),
      ).toHaveLength(1);
      expect(
        (await snapshot(request)).profiles.filter(
          (value) => value.name === name,
        ),
      ).toHaveLength(1);
      expect(observed.errors).toEqual([]);
    } finally {
      released.release();
    }
    await page.unroute("**/api/v1/ai-settings");
    await restore(request, original);
  });
}

test("initial read failure is not an empty list and explicit retry does not write", async ({
  page,
}) => {
  const observed = observe(page);
  let failed = true;
  await page.route("**/api/v1/ai-settings", (route) =>
    failed
      ? route.fulfill({ status: 503, json: { code: "STATE_UNAVAILABLE" } })
      : route.continue(),
  );
  await page.goto("/ai-settings");
  await expect(page.getByText(/Unable to read AI settings/)).toBeVisible();
  await expect(
    page.getByText("No model profiles yet", { exact: true }),
  ).not.toBeVisible();
  await expect(
    page.getByRole("button", { name: "Create profile", exact: true }),
  ).toBeDisabled();
  failed = false;
  await page
    .getByRole("button", { name: "Reload saved settings", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Create profile", exact: true }),
  ).toBeEnabled();
  expect(observed.methods.filter((method) => method === "PUT")).toHaveLength(0);
  expect(observed.errors).toEqual([]);
});

test("the actual ten-second client deadline locks an unacknowledged save without replay", async ({
  page,
  request,
}) => {
  const original = await snapshot(request);
  const observed = observe(page);
  const committed = barrier(),
    released = barrier(),
    settled = barrier();
  await open(page);
  await page.clock.install();
  await page.route("**/api/v1/ai-settings", async (route) => {
    if (route.request().method() !== "PUT") return route.continue();
    const response = await route.fetch();
    expect(response.status()).toBe(200);
    committed.release();
    await released.promise;
    try {
      await route.fulfill({ response });
    } catch {
      /* Browser canceled this held response. */
    } finally {
      settled.release();
    }
  });
  try {
    const dialog = await begin(page, `timeout-${randomUUID()}`);
    await dialog
      .getByRole("button", { name: "Save profile", exact: true })
      .click();
    await committed.promise;
    await page.clock.fastForward(10_001);
    await expect(
      dialog.getByText(/The save was not acknowledged/),
    ).toBeVisible();
    await expect(
      dialog.getByRole("button", { name: "Save profile", exact: true }),
    ).toBeDisabled();
    await dialog.getByRole("button", { name: "Close", exact: true }).click();
    released.release();
    await settled.promise;
    await page
      .getByRole("button", { name: "Reload saved settings", exact: true })
      .click();
    await expect(
      page.getByRole("button", { name: "Create profile", exact: true }),
    ).toBeEnabled();
    expect(observed.methods.filter((method) => method === "PUT")).toHaveLength(
      1,
    );
    expect(observed.errors).toEqual([]);
  } finally {
    released.release();
  }
  await page.unroute("**/api/v1/ai-settings");
  await restore(request, original);
});
