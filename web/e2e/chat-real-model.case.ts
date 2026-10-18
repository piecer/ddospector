import {
  expect,
  test,
  type APIRequestContext,
  type Page,
} from "@playwright/test";
import { existsSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const dir = process.env.CHAT_ACCEPTANCE_DIR!;
const real = process.env.CHAT_ACCEPTANCE_MODE === "real";
const terminal = new Set(["succeeded", "failed", "cancelled", "interrupted"]);
type Turn = {
  id: string;
  session_id: string;
  request_id: string;
  sequence: number;
  revision: number;
  status: string;
  assistant_text: string;
  user_text: string;
  transport: string;
  provider_stop: string;
  error_code: string | null;
  finished_at: string | null;
};
type History = {
  session: { id: string; active_turn_id: string | null };
  turns: Turn[];
  next_before_sequence: number | null;
};
type Message = { role: string; content: string };
type Dispatch = {
  dispatch: number;
  request: {
    model: string;
    stream: boolean;
    max_tokens: number;
    messages: Message[];
  };
};

function artifact(name: string, value: unknown) {
  const pending = join(dir, name + ".pending");
  writeFileSync(pending, JSON.stringify(value, null, 2));
  renameSync(pending, join(dir, name));
}
async function get<T>(request: APIRequestContext, path: string): Promise<T> {
  const response = await request.get("/api/v1/chat/" + path);
  expect(response.status()).toBe(200);
  return response.json() as Promise<T>;
}
async function waitTurn(
  request: APIRequestContext,
  id: string,
  predicate: (turn: Turn) => boolean = (turn) => terminal.has(turn.status),
): Promise<Turn> {
  let current: Turn | undefined;
  await expect
    .poll(
      async () => {
        current = await get<Turn>(request, "turns/" + id);
        return predicate(current);
      },
      { timeout: 125_000, intervals: [100, 250, 500] },
    )
    .toBe(true);
  return current!;
}
async function start(page: Page): Promise<string> {
  await page.getByTestId("chat-new-session").click();
  const response = page.waitForResponse(
    (res) =>
      res.request().method() === "POST" &&
      res.url().endsWith("/api/v1/chat/sessions"),
  );
  await page.getByTestId("chat-start-confirm").click();
  const created = await response;
  expect(created.status()).toBe(201);
  const session = (await created.json()) as { id: string; locale: string };
  expect(session.locale).toBe("ko");
  return session.id;
}
async function send(page: Page, session: string, text: string): Promise<Turn> {
  await page.getByTestId("chat-input").fill(text);
  const response = page.waitForResponse(
    (res) =>
      res.request().method() === "POST" &&
      res.url().endsWith(`/api/v1/chat/sessions/${session}/turns`),
  );
  await page.getByTestId("chat-send").click();
  const accepted = await response;
  expect(accepted.status()).toBe(202);
  await expect(page.getByTestId("chat-input")).toHaveValue("");
  return accepted.json() as Promise<Turn>;
}
async function restored(page: Page, session: string) {
  await page.reload();
  await expect(page.getByTestId("chat-history")).toBeVisible();
  await page.getByTestId("chat-session-" + session).click();
}
async function visibleTurn(page: Page, turn: Turn) {
  await expect(page.getByTestId("chat-transcript")).toContainText(
    turn.user_text,
  );
  if (turn.assistant_text) {
    await expect(page.getByTestId("chat-transcript")).toContainText(
      turn.assistant_text,
    );
  }
  await expect(page.getByTestId("chat-status")).not.toBeEmpty();
}
async function matrix(page: Page, turns: Turn[]) {
  for (const locale of ["en", "ko"]) {
    await page.locator(".language-control select").selectOption(locale);
    await expect(page.locator("html")).toHaveAttribute("lang", locale);
    for (const width of [900, 390]) {
      await page.setViewportSize({ width, height: 1000 });
      for (const turn of turns) await visibleTurn(page, turn);
      const transcript = page.getByTestId("chat-transcript");
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= window.innerWidth + 1,
        ),
      ).toBe(true);
      expect(
        await transcript.evaluate((el) => el.scrollWidth <= el.clientWidth + 1),
      ).toBe(true);
      expect((await transcript.getAttribute("aria-live")) ?? "").not.toMatch(
        /polite|assertive/,
      );
      expect(
        await transcript
          .locator('[aria-live="polite"], [aria-live="assertive"]')
          .count(),
      ).toBe(0);
      const status = page.getByTestId("chat-status");
      expect(
        (await status.getAttribute("role")) === "status" ||
          ["polite", "assertive"].includes(
            (await status.getAttribute("aria-live")) ?? "",
          ),
      ).toBe(true);
      const input = page.getByTestId("chat-input");
      await input.focus();
      await expect(input).toBeFocused();
      await input.fill("unsent keyboard check");
      await input.press("Shift+Enter");
      await expect(input).toHaveValue("unsent keyboard check\n");
      await input.press("Tab");
      expect(
        await page.evaluate(() => document.activeElement !== document.body),
      ).toBe(true);
      await input.fill("");
      const stored = await page.evaluate(() => Object.values(localStorage));
      for (const turn of turns) {
        expect(stored.some((value) => value.includes(turn.user_text))).toBe(
          false,
        );
        if (turn.assistant_text)
          expect(
            stored.some((value) => value.includes(turn.assistant_text)),
          ).toBe(false);
      }
      await page.screenshot({
        path: join(dir, `chat-${locale}-${width}.png`),
        fullPage: true,
      });
    }
  }
}

// One scenario, one transcript. No viewport projects repeating paid inference.
test(
  real
    ? "selected real model: four finite UI turns"
    : "SYNTHETIC fixture UI and protocol error",
  async ({ page, request }) => {
    const errors: string[] = [];
    const requests: { method: string; path: string }[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    page.on("request", (req) => {
      const url = new URL(req.url());
      requests.push({ method: req.method(), path: url.pathname });
      expect(url.port).not.toBe("11434"); // Providers must never be called by browser.
    });
    const turns: Turn[] = [];
    try {
      await page.goto("/agent");
      await page.locator(".language-control select").selectOption("ko");
      const before = await get<{ sessions: unknown[] }>(request, "sessions");
      expect(before.sessions).toEqual([]); // mounting is not consent
      const session = await start(page);
      const firstText = real
        ? "한국어로 짧게 인사하고, 대화의 암호가 청록색 등대임을 기억해 주세요."
        : "SYNTHETIC browser first turn";
      const initial = await send(page, session, firstText);
      const first = await waitTurn(request, initial.id);
      expect(first.status).toBe("succeeded");
      expect(first.assistant_text.trim().length).toBeGreaterThan(0);
      expect(first.error_code).toBeNull();
      expect(first.transport).toBe("closed");
      expect(first.provider_stop).toBe("unknown");
      await expect(page.getByTestId("chat-status")).toContainText(
        /complete|succeeded|done|완료|성공/i,
      );
      turns.push(first);
      await visibleTurn(page, first);
      await restored(page, session);
      await visibleTurn(page, first);

      const secondText = real
        ? "방금 말한 암호를 기억하나요? 한국어 한 문장으로 답해 주세요."
        : "SYNTHETIC missing upstream terminal";
      const second = await waitTurn(
        request,
        (await send(page, session, secondText)).id,
      );
      turns.push(second);
      if (!real) {
        expect(second.status).toBe("failed");
        expect(second.error_code).toBe("CHAT_PROVIDER_PROTOCOL");
        await expect(page.getByTestId("chat-status")).toContainText(
          /failed|error|실패|오류/i,
        );
        await visibleTurn(page, second);
        await matrix(page, turns);
        expect(errors).toEqual([]);
        return;
      }
      expect(second.status).toBe("succeeded");
      expect(second.assistant_text.trim().length).toBeGreaterThan(0);
      await visibleTurn(page, second);
      // Actual backend dispatch observation, not a guessed LLM answer match.
      const dispatches = JSON.parse(
        readFileSync(join(dir, "dispatches.json"), "utf8"),
      ) as Dispatch[];
      expect(dispatches).toHaveLength(2);
      expect(dispatches[1].request.messages.slice(-3)).toEqual([
        { role: "user", content: firstText },
        { role: "assistant", content: first.assistant_text },
        { role: "user", content: secondText },
      ]);
      expect(dispatches[1].request.messages[0].role).toBe("system");
      expect(dispatches[1].request.model).toBe("qwen3.8:27b");
      await restored(page, session);
      for (const turn of turns) await visibleTurn(page, turn);
      const history = await get<History>(request, `sessions/${session}`);
      expect(history.turns).toEqual(turns);
      await matrix(page, turns);

      const stopTurn = await send(
        page,
        session,
        "한국어로 바다에 관한 긴 이야기를 써 주세요. 여러 단락으로 자세히 계속해 주세요.",
      );
      const partial = await waitTurn(
        request,
        stopTurn.id,
        (turn) => turn.status === "running" && turn.assistant_text.length > 0,
      );
      await page.getByTestId("chat-stop").click();
      const stopped = await waitTurn(request, stopTurn.id);
      expect(stopped.status).toBe("cancelled");
      expect(stopped.error_code).toBe("CHAT_CANCELLED");
      expect(stopped.transport).toBe("closed");
      expect(stopped.provider_stop).toBe("unknown");
      await expect(page.getByTestId("chat-status")).toContainText(
        /stopped|cancelled|canceled|중지|취소/i,
      );
      expect(stopped.assistant_text.startsWith(partial.assistant_text)).toBe(
        true,
      );
      turns.push(stopped);
      await visibleTurn(page, stopped);

      const restartTurn = await send(
        page,
        session,
        "한국어로 우주 탐사에 관한 긴 이야기를 써 주세요. 여러 단락으로 계속해 주세요.",
      );
      await waitTurn(
        request,
        restartTurn.id,
        (turn) => turn.status === "running" && turn.assistant_text.length > 0,
      );
      artifact("restart-request.json", { turn_id: restartTurn.id });
      await expect
        .poll(() => existsSync(join(dir, "restart-ready.json")), {
          timeout: 30_000,
        })
        .toBe(true);
      const interrupted = await get<Turn>(request, "turns/" + restartTurn.id);
      const committed = JSON.parse(
        readFileSync(join(dir, "pre-restart-turn.json"), "utf8"),
      ) as Turn;
      expect(interrupted.status).toBe("interrupted");
      expect(interrupted.error_code).toBe("CHAT_INTERRUPTED");
      // Streaming may commit between the last GET and SIGKILL. Preserve every
      // observed committed byte; do not pretend that read froze the producer.
      expect(
        interrupted.assistant_text.startsWith(committed.assistant_text),
      ).toBe(true);
      expect(interrupted.revision).toBeGreaterThan(committed.revision);
      expect(interrupted.transport).toBe("unknown");
      expect(interrupted.provider_stop).toBe("unknown");
      turns.push(interrupted);
      await restored(page, session);
      await visibleTurn(page, interrupted);
      await expect(page.getByTestId("chat-status")).toContainText(
        /interrupted|중단/i,
      );
      const latest = await get<History>(request, `sessions/${session}`);
      expect(latest.turns).toEqual(turns.slice(2));
      expect(latest.session.active_turn_id).toBeNull();
      await page.getByTestId("chat-older").click();
      for (const turn of turns.slice(0, 2)) await visibleTurn(page, turn);
      await page.getByTestId("chat-newest").click();
      await visibleTurn(page, interrupted);
      const finalDispatches = JSON.parse(
        readFileSync(join(dir, "dispatches.json"), "utf8"),
      ) as Dispatch[];
      expect(finalDispatches).toHaveLength(4);
      expect(finalDispatches[3].request.messages.slice(1, -1)).toEqual([
        { role: "user", content: firstText },
        { role: "assistant", content: first.assistant_text },
        { role: "user", content: secondText },
        { role: "assistant", content: second.assistant_text },
      ]); // cancelled exchange is excluded, not invisibly summarized
      const preview = await request.post("/api/v1/agent/preview", {
        data: { goal: "Acceptance preview only", locale: "ko" },
      });
      expect(preview.status()).toBe(200);
      expect((await preview.json()).origin).toBe(
        "deterministic_context_preview",
      );
      for (const [path, code] of [
        ["runs", "LIVE_NOT_AVAILABLE"],
        ["agent/execute", "AGENT_EXECUTION_NOT_AVAILABLE"],
        ["ai-settings/test", "AI_CONNECTION_NOT_AVAILABLE"],
      ]) {
        const response = await request.post("/api/v1/" + path, { data: {} });
        expect(response.status()).toBeGreaterThanOrEqual(400);
        expect((await response.json()).code).toBe(code);
      }
      expect(
        requests.filter(
          (value) =>
            value.method === "POST" &&
            /\/sessions\/[^/]+\/turns$/.test(value.path),
        ),
      ).toHaveLength(4);
      expect(errors).toEqual([]);
    } finally {
      artifact("browser-observations.json", {
        mode: real ? "real" : "synthetic-fixture",
        turns,
        requests,
        pageErrors: errors,
      });
    }
  },
);
