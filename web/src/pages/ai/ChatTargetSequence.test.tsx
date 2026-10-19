import { afterEach, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ChatPanel } from "./ChatPanel";
import { response, runtimeFixture, session } from "./chat-test-fixtures";
import { targetRuntime } from "./chat-target-test-fixtures";
import { fence } from "./chat-tool-test-fixtures";

afterEach(() => vi.unstubAllGlobals());

function fixture() {
  // Synthetic metadata only. Every unexpected request (including a grant or
  // turn before explicit consent) fails instead of receiving a success stub.
  const fetch = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith("/tools/runtime")) return response(targetRuntime);
    if (url.endsWith("/tools/fence")) return response(fence);
    if (url.endsWith("/runtime")) return response(runtimeFixture);
    if (url.endsWith("/sessions") && init?.method === "GET")
      return response({ schema_version: 1, sessions: [] });
    if (url.endsWith("/sessions") && init?.method === "POST") {
      const value = JSON.parse(String(init.body));
      return response(
        {
          ...session,
          request_id: value.request_id,
          locale: value.locale,
          sequence: 0,
          active_turn_id: null,
        },
        201,
      );
    }
    throw new Error("Unexpected request " + url);
  });
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

async function start(locale: "en" | "ko") {
  render(<ChatPanel locale={locale} />);
  await waitFor(() =>
    expect(screen.getByTestId("chat-new-session")).toBeEnabled(),
  );
  fireEvent.click(screen.getByTestId("chat-new-session"));
  fireEvent.click(screen.getByTestId("chat-start-confirm"));
  await waitFor(() => expect(screen.getByTestId("chat-input")).toBeEnabled());
}

it.each(["en", "ko"] as const)(
  "without availability, target selection stays Agent with unchecked consent (%s)",
  async (locale) => {
    const fetch = fixture();
    await start(locale);
    expect(screen.getByTestId("chat-tools-toggle")).not.toBeChecked();
    expect(
      screen.getByRole("option", {
        name: locale === "en" ? "Create target" : "대상 생성",
      }),
    ).toBeDisabled();
    fireEvent.change(screen.getByTestId("chat-tool-scope"), {
      target: { value: "target_create_v2" },
    });
    expect(screen.getByTestId("chat-tool-scope")).toHaveValue("agent_v1");
    expect(screen.getByTestId("chat-tools-toggle")).not.toBeChecked();
    expect(
      fetch.mock.calls.filter(([url]) =>
        /\/(tools\/(runtime|fence)|tool-grants|tool-turns)$/.test(url),
      ),
    ).toHaveLength(0);
  },
);

it.each(["en", "ko"] as const)(
  "explicit availability enables target-labelled consent without granting it (%s)",
  async (locale) => {
    const fetch = fixture();
    await start(locale);
    expect(screen.getByTestId("chat-tools-toggle")).not.toBeChecked();
    fireEvent.click(
      screen.getByRole("button", {
        name:
          locale === "en"
            ? "Read tool availability / fence"
            : "도구 사용 가능 여부 / 차단 읽기",
      }),
    );
    await waitFor(() =>
      expect(
        screen.getByRole("option", {
          name: locale === "en" ? "Create target" : "대상 생성",
        }),
      ).toBeEnabled(),
    );
    fireEvent.change(screen.getByTestId("chat-tool-scope"), {
      target: { value: "target_create_v2" },
    });
    expect(screen.getByTestId("chat-tool-scope")).toHaveValue("target_create_v2");
    expect(screen.getByTestId("chat-tools-toggle")).toHaveAccessibleName(
      locale === "en"
        ? "For the exact next message only: allow target reads and one target creation proposal. No write authority; separate exact approval is required."
        : "정확히 다음 메시지만: 대상 읽기와 대상 생성 제안 1건에 동의합니다. 저장 권한이 아니며 정확한 제안에 별도 승인이 필요합니다.",
    );
    expect(screen.getByTestId("chat-tools-toggle")).not.toBeChecked();
    for (const path of ["/tools/runtime", "/tools/fence"])
      expect(fetch.mock.calls.filter(([url]) => url.endsWith(path))).toHaveLength(
        1,
      );
    expect(
      fetch.mock.calls.filter(([url, init]) =>
        init?.method === "POST" && !url.endsWith("/sessions"),
      ),
    ).toHaveLength(0);
  },
);
