import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { MouseEvent as ReactMouseEvent } from "react";
import * as ui from "../../components/ui";
import { ProfilesPage } from "../lab/profiles";
import { workspaceFixture } from "../../test/fixtures";
import type { Locale, PageProps } from "../../lib/contracts";
import { recordFixture } from "./testRecords";
const empty = {
  revision: 0,
  total: 0,
  offset: 0,
  limit: 50,
  items: [],
  execution_enabled: false,
};
const reply = (v: unknown, status = 200) =>
  new Response(JSON.stringify(v), { status });
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});
async function pageProps(locale: Locale = "en"): Promise<PageProps> {
  const record = await recordFixture();
  const data = workspaceFixture();
  data.targets = [record.target_snapshot, record.sink_snapshot];
  data.profiles = [record.profile_snapshot];
  return {
    data,
    locale,
    navigate: vi.fn(),
    refresh: vi.fn().mockResolvedValue(undefined),
  };
}
it("mounts an independent scenario library without replacing template detail behavior", async () => {
  const fetcher = vi.fn().mockResolvedValue(reply(empty));
  vi.stubGlobal("fetch", fetcher);
  render(<ProfilesPage {...await pageProps()} />);
  expect(
    await screen.findByRole("heading", { name: "Scenario library" }),
  ).toBeInTheDocument();
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "New scenario" })).toBeEnabled(),
  );
  expect(
    screen.getByRole("heading", { name: "Packet replay policy check" }),
  ).toBeInTheDocument();
  expect(fetcher).toHaveBeenCalledTimes(1);
});
it("distinguishes initial read failure from empty and missing DUT/SINK prerequisites", async () => {
  const fetcher = vi
    .fn()
    .mockRejectedValueOnce(new Error("offline"))
    .mockResolvedValue(reply(empty));
  vi.stubGlobal("fetch", fetcher);
  const props = await pageProps();
  props.data.targets = [];
  render(<ProfilesPage {...props} />);
  expect(
    await screen.findByText(
      "The scenario library could not be read. Writes are disabled.",
    ),
  ).toBeInTheDocument();
  expect(
    screen.queryByText("No scenario definitions yet."),
  ).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Retry read" }));
  expect(
    await screen.findByText("No scenario definitions yet."),
  ).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "New scenario" })).toBeDisabled();
  fireEvent.click(
    screen.getByRole("button", { name: "Configure scenario targets" }),
  );
  expect(props.navigate).toHaveBeenCalledWith("targets");
});
const formLabels = {
  en: [
    "Scenario name",
    "Objective",
    "DUT version",
    "Policy version",
    "Maximum PPS",
    "Maximum BPS",
    "Maximum packets",
    "Maximum bytes",
    "Maximum connections",
    "Duration (seconds)",
    "Minimum delivery (%)",
    "Maximum delivery (%)",
    "Maximum legitimate loss (%)",
    "Maximum service latency (ms)",
  ],
  ko: [
    "시나리오 이름",
    "목표",
    "DUT 버전",
    "정책 버전",
    "최대 PPS",
    "최대 BPS",
    "최대 패킷 수",
    "최대 바이트 수",
    "최대 연결 수",
    "지속 시간(초)",
    "최소 전달률(%)",
    "최대 전달률(%)",
    "정상 트래픽 최대 손실률(%)",
    "최대 서비스 지연(ms)",
  ],
};
function fillForm(locale: Locale) {
  const values = [
    " Policy 🧪 ",
    " Observe\npolicy\t ",
    " firmware ",
    " policy ",
    "100",
    "1000",
    "1000",
    "10000",
    "10",
    "10",
    "95",
    "100",
    "1",
    "100",
  ];
  formLabels[locale].forEach((label, i) =>
    fireEvent.change(screen.getByLabelText(label), {
      target: { value: values[i] },
    }),
  );
  fireEvent.change(
    screen.getByLabelText(locale === "en" ? "DUT target" : "DUT 대상"),
    { target: { value: "dut-test" } },
  );
  fireEvent.change(
    screen.getByLabelText(locale === "en" ? "Sink target" : "수신 대상"),
    { target: { value: "sink-test" } },
  );
  for (const label of locale === "en"
    ? ["Ingress PCAP", "Egress PCAP", "Service probe"]
    : ["앞단 PCAP", "뒷단 PCAP", "정상 서비스 프로브"])
    fireEvent.click(screen.getByLabelText(label));
}
it.each(["en", "ko"] as const)(
  "creates through real localized controls with exact literals and history acknowledgement in %s",
  async (locale) => {
    let saved: Awaited<ReturnType<typeof recordFixture>> | null = null;
    const fetcher = vi.fn(async (url: string, options: RequestInit) => {
      if (options.method === "POST") {
        const input = JSON.parse(options.body as string);
        expect(input.revision).toBe(0);
        saved = await recordFixture(1, { definition: input.definition });
        return reply(
          { revision: 1, scenario: saved, execution_enabled: false },
          201,
        );
      }
      if (url.includes("?"))
        return reply(
          saved ? { ...empty, revision: 1, total: 1, items: [saved] } : empty,
        );
      return reply({
        revision: 1,
        scenario_id: saved!.id,
        versions: [saved],
        execution_enabled: false,
      });
    });
    vi.stubGlobal("fetch", fetcher);
    render(<ProfilesPage {...await pageProps(locale)} />);
    const newButton = screen.getByRole("button", {
      name: locale === "en" ? "New scenario" : "새 시나리오",
    });
    await waitFor(() => expect(newButton).toBeEnabled());
    fireEvent.click(newButton);
    expect(
      screen.getByLabelText(locale === "en" ? "Maximum PPS" : "최대 PPS"),
    ).toHaveValue(null);
    fillForm(locale);
    for (const label of locale === "en"
      ? [
          "Detection deadline (ms)",
          "Maximum CPU (%)",
          "Maximum memory (%)",
          "Maximum sessions",
        ]
      : [
          "탐지 제한 시간(ms)",
          "최대 CPU 사용률(%)",
          "최대 메모리 사용률(%)",
          "최대 세션 수",
        ])
      expect(screen.getByLabelText(label)).toHaveValue(null);
    fireEvent.click(
      screen.getByRole("button", {
        name: locale === "en" ? "Save scenario" : "시나리오 저장",
      }),
    );
    expect(
      await screen.findByText(
        locale === "en"
          ? "Scenario saved and verified in immutable history. No execution was started."
          : "불변 이력에서 시나리오 저장을 확인했습니다. 실행은 시작되지 않았습니다.",
      ),
    ).toBeInTheDocument();
    const body = JSON.parse(
      fetcher.mock.calls.find(([, init]) => init.method === "POST")![1]
        .body as string,
    );
    expect(body.definition).toEqual((await recordFixture()).definition);
    expect(fetcher.mock.calls.map(([, init]) => init.method)).toEqual([
      "GET",
      "POST",
      "GET",
      "GET",
    ]);
  },
);
it("inspects immutable history and edits the latest version using the revision opened, not ambient state", async () => {
  const one = await recordFixture();
  const versions = [one];
  const original = JSON.stringify(one);
  const fetcher = vi.fn(async (url: string, init: RequestInit) => {
    if (init.method === "PUT") {
      const input = JSON.parse(init.body as string);
      expect(input.revision).toBe(1);
      versions.push(await recordFixture(2, { definition: input.definition }));
      return reply({
        revision: 2,
        scenario: versions[1],
        execution_enabled: false,
      });
    }
    if (url.includes("?"))
      return reply({
        ...empty,
        total: 1,
        revision: versions.length,
        items: [versions.at(-1)],
      });
    return reply({
      revision: versions.length,
      scenario_id: one.id,
      versions,
      execution_enabled: false,
    });
  });
  vi.stubGlobal("fetch", fetcher);
  const props = await pageProps();
  const view = render(<ProfilesPage {...props} />);
  fireEvent.click(
    await screen.findByRole("button", { name: "Scenario history" }),
  );
  const history = await screen.findByLabelText("Revision");
  expect(history).toHaveValue("1");
  expect(
    within(screen.getByRole("dialog")).getByText(one.digest),
  ).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Edit scenario" }));
  expect(screen.getByLabelText("Scenario name")).toHaveValue(
    one.definition.name,
  );
  fireEvent.change(screen.getByLabelText("Scenario name"), {
    target: { value: " Second literal " },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save new version" }));
  expect(
    await screen.findByText(
      "Scenario saved and verified in immutable history. No execution was started.",
    ),
  ).toBeInTheDocument();
  expect(JSON.stringify(one)).toBe(original);
  view.rerender(
    <ProfilesPage {...props} data={{ ...props.data, targets: [] }} />,
  );
  fireEvent.click(screen.getByRole("button", { name: "Scenario history" }));
  fireEvent.change(await screen.findByLabelText("Revision"), {
    target: { value: "1" },
  });
  expect(
    within(screen.getByRole("dialog")).getByText(one.digest),
  ).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Edit scenario" })).toBeDisabled();
});
it("makes all entries reachable through bounded pagination", async () => {
  const records = await Promise.all(
    Array.from({ length: 51 }, (_, i) =>
      recordFixture(1, {
        id: `${String(i).padStart(8, "0")}-1111-4111-8111-111111111111`,
      }),
    ),
  );
  const fetcher = vi.fn(async (url: string) => {
    const offset = Number(
      new URL(url, "http://test.invalid").searchParams.get("offset"),
    );
    return reply({
      ...empty,
      revision: 51,
      total: 51,
      offset,
      items: records.slice(offset, offset + 50),
    });
  });
  vi.stubGlobal("fetch", fetcher);
  render(<ProfilesPage {...await pageProps()} />);
  await waitFor(() =>
    expect(
      screen.getAllByRole("button", { name: "Scenario history" }),
    ).toHaveLength(50),
  );
  fireEvent.click(screen.getByRole("button", { name: "Next page" }));
  await waitFor(() =>
    expect(
      screen.getAllByRole("button", { name: "Scenario history" }),
    ).toHaveLength(1),
  );
  expect(screen.getByText(records[50].id)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Next page" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Previous page" }));
  await waitFor(() =>
    expect(
      screen.getAllByRole("button", { name: "Scenario history" }),
    ).toHaveLength(50),
  );
});
it.each([
  "SCENARIO_CONFLICT",
  "SCENARIO_STATE_UNAVAILABLE",
  "SCENARIO_COMMIT_UNCERTAIN",
  "wrong-definition",
  "wrong-digest",
])(
  "keeps %s saves read-only without write replay on explicit GET retry",
  async (failure) => {
    const record = await recordFixture();
    const fetcher = vi.fn(async (_url: string, init: RequestInit) => {
      if (init.method === "POST") {
        if (failure.startsWith("SCENARIO_"))
          return reply(
            { code: failure, message: "fixed" },
            failure === "SCENARIO_CONFLICT" ? 409 : 503,
          );
        const wrong =
          failure === "wrong-digest"
            ? { ...record, digest: "0".repeat(64) }
            : await recordFixture(1, {
                definition: { ...record.definition, name: "other definition" },
              });
        return reply(
          { revision: 1, scenario: wrong, execution_enabled: false },
          201,
        );
      }
      return reply(empty);
    });
    vi.stubGlobal("fetch", fetcher);
    render(<ProfilesPage {...await pageProps()} />);
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "New scenario" }),
      ).toBeEnabled(),
    );
    fireEvent.click(screen.getByRole("button", { name: "New scenario" }));
    fillForm("en");
    fireEvent.click(screen.getByRole("button", { name: "Save scenario" }));
    const retry = await screen.findByRole("button", {
      name: "Retry acknowledgement read",
    });
    expect(screen.getByLabelText("Scenario name")).toHaveAttribute("readonly");
    expect(screen.getByLabelText("Scenario name")).toHaveValue(" Policy 🧪 ");
    expect(
      screen.getByRole("button", { name: "Save scenario" }),
    ).toBeDisabled();
    fireEvent.click(retry);
    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(3));
    expect(
      screen.queryByText(
        "Scenario saved and verified in immutable history. No execution was started.",
      ),
    ).not.toBeInTheDocument();
    expect(screen.getByLabelText("Scenario name")).toHaveValue(" Policy 🧪 ");
    expect(fetcher.mock.calls.map(([, init]) => init.method)).toEqual([
      "GET",
      "POST",
      "GET",
    ]);
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Discard draft and reopen" }),
      ).toBeEnabled(),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Discard draft and reopen" }),
    );
    await waitFor(() =>
      expect(screen.getByLabelText("Scenario name")).toHaveValue(""),
    );
    const save = screen.getByRole("button", { name: "Save scenario" });
    if (
      failure === "SCENARIO_STATE_UNAVAILABLE" ||
      failure === "SCENARIO_COMMIT_UNCERTAIN"
    ) {
      expect(save).toBeDisabled();
      expect(screen.getByLabelText("Scenario name")).toHaveAttribute(
        "readonly",
      );
    } else expect(save).toBeEnabled();
  },
);
const storageFailures = [
  "SCENARIO_STATE_UNAVAILABLE",
  "SCENARIO_COMMIT_UNCERTAIN",
] as const;
const storageNotices = {
  en: "Scenario writes are blocked after a storage failure. Acknowledgement reads only check saved history; they do not recover storage or unlock writes. Operator storage recovery is required. Reloading this page only clears this UI observation; the API still decides whether writes are safe.",
  ko: "저장소 오류로 시나리오 저장을 차단했습니다. 저장 확인 읽기는 저장된 이력만 확인하며 저장소를 복구하거나 저장 차단을 해제하지 않습니다. 운영자의 저장소 복구가 필요합니다. 페이지 전체 새로고침은 이 UI의 오류 관찰만 초기화하며, 저장 허용 여부는 API가 판단합니다.",
};
it.each(
  storageFailures.flatMap((code) =>
    (["en", "ko"] as const).flatMap((locale) =>
      (["POST", "PUT"] as const).map((method) => ({ code, locale, method })),
    ),
  ),
)(
  "keeps $code $method writes blocked through the read-only lifecycle in $locale",
  async ({ code, locale, method }) => {
    const one = await recordFixture(),
      two = await recordFixture(2);
    const fetcher = vi.fn(async (url: string, init: RequestInit) => {
      if (init.method !== "GET") return reply({ code, message: "fixed" }, 503);
      return reply(
        url.includes("?")
          ? { ...empty, revision: 2, total: 1, items: [two] }
          : {
              revision: 2,
              scenario_id: one.id,
              versions: [one, two],
              execution_enabled: false,
            },
      );
    });
    vi.stubGlobal("fetch", fetcher);
    render(<ProfilesPage {...await pageProps(locale)} />);
    const c = (en: string, ko: string) => (locale === "en" ? en : ko);
    const button = (en: string, ko: string) =>
      screen.getByRole("button", { name: c(en, ko) });
    const name = () =>
      screen.getByLabelText(c("Scenario name", "시나리오 이름"));
    const save = () =>
      button(
        method === "POST" ? "Save scenario" : "Save new version",
        method === "POST" ? "시나리오 저장" : "새 버전 저장",
      );
    await waitFor(() =>
      expect(button("New scenario", "새 시나리오")).toBeEnabled(),
    );
    if (method === "POST") {
      fireEvent.click(button("New scenario", "새 시나리오"));
      fillForm(locale);
    } else {
      fireEvent.click(button("Scenario history", "시나리오 이력"));
      await screen.findByLabelText(c("Revision", "리비전"));
      fireEvent.click(button("Edit scenario", "시나리오 수정"));
    }
    const literal = ` Preserved ${method} 🧪 `;
    fireEvent.change(name(), { target: { value: literal } });
    fireEvent.click(save());
    await screen.findByRole("button", {
      name: c("Retry acknowledgement read", "저장 확인 읽기 재시도"),
    });
    expect(save()).toBeDisabled();
    expect(name()).toHaveAttribute("readonly");
    expect(name()).toBeEnabled();
    const input = name() as HTMLInputElement;
    input.focus();
    input.select();
    expect(input).toHaveFocus();
    expect(input.value.slice(input.selectionStart!, input.selectionEnd!)).toBe(
      literal,
    );
    fireEvent.change(name(), { target: { value: "not the preserved draft" } });
    expect(name()).toHaveValue(literal);
    fireEvent.submit(save().closest("form")!);
    fireEvent(
      screen.getByRole("dialog"),
      new Event("cancel", { bubbles: true, cancelable: true }),
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    fireEvent.click(button("Review preserved draft", "보존된 초안 검토"));
    expect(name()).toHaveValue(literal);
    fireEvent.click(
      button("Retry acknowledgement read", "저장 확인 읽기 재시도"),
    );
    await waitFor(() =>
      expect(
        button("Discard draft and reopen", "초안 버리고 다시 열기"),
      ).toBeEnabled(),
    );
    expect(name()).toHaveValue(literal);
    expect(save()).toBeDisabled();
    expect(
      screen.getByText(
        c("Opening registry revision: 2", "열 때의 레지스트리 리비전: 2"),
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(
        c(
          "Scenario saved and verified in immutable history. No execution was started.",
          "불변 이력에서 시나리오 저장을 확인했습니다. 실행은 시작되지 않았습니다.",
        ),
      ),
    ).not.toBeInTheDocument();
    fireEvent.click(
      button("Discard draft and reopen", "초안 버리고 다시 열기"),
    );
    await waitFor(() =>
      expect(name()).toHaveValue(method === "POST" ? "" : two.definition.name),
    );
    // These guards must survive the newly opened session's editing phase.
    expect(save()).toBeDisabled();
    expect(name()).toHaveAttribute("readonly");
    expect(screen.getByLabelText(c("DUT target", "DUT 대상"))).toBeDisabled();
    expect(
      screen.getByLabelText(c("Service probe", "정상 서비스 프로브")),
    ).toBeDisabled();
    fireEvent.change(name(), { target: { value: "must not edit" } });
    expect(name()).toHaveValue(method === "POST" ? "" : two.definition.name);
    fireEvent.submit(save().closest("form")!);
    expect(
      within(screen.getByRole("dialog")).getByText(storageNotices[locale]),
    ).toBeInTheDocument();
    fireEvent.click(button("Close", "닫기"));
    expect(button("New scenario", "새 시나리오")).toBeDisabled();
    // Read navigation stays usable even while the closed draft is retained.
    expect(button("Reload scenarios", "시나리오 새로고침")).toBeEnabled();
    expect(button("Scenario history", "시나리오 이력")).toBeEnabled();
    fireEvent.click(button("Scenario history", "시나리오 이력"));
    const revision = await screen.findByLabelText(c("Revision", "리비전"));
    expect(revision).toHaveValue("2");
    expect(
      within(screen.getByRole("dialog")).getByText(two.digest),
    ).toBeInTheDocument();
    fireEvent.change(revision, { target: { value: "1" } });
    expect(
      within(screen.getByRole("dialog")).getByText(one.digest),
    ).toBeInTheDocument();
    fireEvent.change(revision, { target: { value: "2" } });
    expect(button("Edit scenario", "시나리오 수정")).toBeDisabled();
    fireEvent.click(button("Close", "닫기"));
    fireEvent.click(button("Review preserved draft", "보존된 초안 검토"));
    expect(save()).toBeDisabled();
    fireEvent.click(button("Discard draft", "초안 버리기"));
    // Now no session exists: the storage latch alone blocks create and edit.
    expect(button("New scenario", "새 시나리오")).toBeDisabled();
    fireEvent.click(button("New scenario", "새 시나리오"));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    fireEvent.click(button("Reload scenarios", "시나리오 새로고침"));
    await screen.findByRole("button", {
      name: c("Scenario history", "시나리오 이력"),
    });
    expect(button("New scenario", "새 시나리오")).toBeDisabled();
    expect(screen.getByText(storageNotices[locale])).toBeInTheDocument();
    fireEvent.click(button("Scenario history", "시나리오 이력"));
    await screen.findByLabelText(c("Revision", "리비전"));
    expect(button("Edit scenario", "시나리오 수정")).toBeDisabled();
    fireEvent.click(button("Edit scenario", "시나리오 수정"));
    expect(
      screen.getByRole("dialog", {
        name: c("Scenario history", "시나리오 이력"),
      }),
    ).toBeInTheDocument();
    expect(
      screen.queryByLabelText(c("Scenario name", "시나리오 이름")),
    ).not.toBeInTheDocument();
    fireEvent.click(button("Close", "닫기"));
    await act(async () => {});
    const mutations = fetcher.mock.calls.filter(
      ([, init]) => init.method !== "GET",
    );
    expect(mutations).toHaveLength(1);
    expect(mutations[0][0]).toBe(
      "/api/v1/scenarios" + (method === "PUT" ? "/" + one.id : ""),
    );
    expect(mutations[0][1].method).toBe(method);
    expect(JSON.parse(mutations[0][1].body as string)).toMatchObject({
      revision: 2,
      definition: { name: literal },
    });
    expect(fetcher.mock.calls.map(([, init]) => init.method)).toEqual([
      "GET",
      ...(method === "PUT" ? ["GET"] : []),
      method,
      "GET",
      "GET",
      ...(method === "PUT" ? ["GET"] : []),
      "GET",
      "GET",
      "GET",
    ]);
  },
);
it("guards create and edit handlers independently of the disabled DOM buttons", async () => {
  const realButton = ui.Button;
  let createHandler:
    ((event: ReactMouseEvent<HTMLButtonElement>) => void) | undefined;
  let editHandler:
    ((event: ReactMouseEvent<HTMLButtonElement>) => void) | undefined;
  // Retain real DOM controls, but also exercise the guarded callbacks directly.
  vi.spyOn(ui, "Button").mockImplementation((props) => {
    if (props.children === "New scenario") createHandler = props.onClick;
    if (props.children === "Edit scenario") editHandler = props.onClick;
    return realButton(props);
  });
  const one = await recordFixture();
  const fetcher = vi.fn(async (url: string, init: RequestInit) => {
    if (init.method === "POST")
      return reply(
        { code: "SCENARIO_COMMIT_UNCERTAIN", message: "fixed" },
        503,
      );
    return reply(
      url.includes("?")
        ? { ...empty, revision: 1, total: 1, items: [one] }
        : {
            revision: 1,
            scenario_id: one.id,
            versions: [one],
            execution_enabled: false,
          },
    );
  });
  vi.stubGlobal("fetch", fetcher);
  render(<ProfilesPage {...await pageProps()} />);
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "New scenario" })).toBeEnabled(),
  );
  fireEvent.click(screen.getByRole("button", { name: "New scenario" }));
  fillForm("en");
  fireEvent.click(screen.getByRole("button", { name: "Save scenario" }));
  fireEvent.click(
    await screen.findByRole("button", { name: "Discard draft and reopen" }),
  );
  await waitFor(() =>
    expect(screen.getByLabelText("Scenario name")).toHaveValue(""),
  );
  fireEvent.click(screen.getByRole("button", { name: "Discard draft" }));
  expect(screen.getByRole("button", { name: "New scenario" })).toBeDisabled();
  expect(createHandler).toBeTypeOf("function");
  await act(async () =>
    createHandler!(
      new MouseEvent("click") as unknown as ReactMouseEvent<HTMLButtonElement>,
    ),
  );
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Scenario history" }));
  await screen.findByLabelText("Revision");
  expect(screen.getByRole("button", { name: "Edit scenario" })).toBeDisabled();
  expect(editHandler).toBeTypeOf("function");
  await act(async () =>
    editHandler!(
      new MouseEvent("click") as unknown as ReactMouseEvent<HTMLButtonElement>,
    ),
  );
  expect(
    screen.getByRole("dialog", { name: "Scenario history" }),
  ).toBeInTheDocument();
  expect(screen.queryByLabelText("Scenario name")).not.toBeInTheDocument();
  expect(fetcher.mock.calls.map(([, init]) => init.method)).toEqual([
    "GET",
    "POST",
    "GET",
    "GET",
  ]);
});
it.each(storageFailures)(
  "keeps %s GET readback failure distinct from a mutation storage failure",
  async (code) => {
    const one = await recordFixture();
    let saved = false,
      histories = 0;
    const fetcher = vi.fn(async (url: string, init: RequestInit) => {
      if (init.method === "POST") {
        saved = true;
        return reply(
          { revision: 1, scenario: one, execution_enabled: false },
          201,
        );
      }
      if (url.includes("?"))
        return reply(
          saved ? { ...empty, revision: 1, total: 1, items: [one] } : empty,
        );
      if (++histories === 1) return reply({ code, message: "fixed" }, 503);
      return reply({
        revision: 1,
        scenario_id: one.id,
        versions: [one],
        execution_enabled: false,
      });
    });
    vi.stubGlobal("fetch", fetcher);
    render(<ProfilesPage {...await pageProps()} />);
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "New scenario" }),
      ).toBeEnabled(),
    );
    fireEvent.click(screen.getByRole("button", { name: "New scenario" }));
    fillForm("en");
    fireEvent.click(screen.getByRole("button", { name: "Save scenario" }));
    const retry = await screen.findByRole("button", {
      name: "Retry acknowledgement read",
    });
    expect(screen.queryByText(storageNotices.en)).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Save scenario" }),
    ).toBeDisabled();
    fireEvent.click(retry);
    await screen.findByText(
      "Scenario saved and verified in immutable history. No execution was started.",
    );
    expect(screen.getByRole("button", { name: "New scenario" })).toBeEnabled();
    expect(screen.queryByText(storageNotices.en)).not.toBeInTheDocument();
    expect(fetcher.mock.calls.map(([, init]) => init.method)).toEqual([
      "GET",
      "POST",
      "GET",
      "GET",
      "GET",
    ]);
  },
);
it.each(storageFailures)(
  "retains %s across prop changes but a fresh mount clears only the UI observation",
  async (code) => {
    const fetcher = vi.fn(async (_url: string, init: RequestInit) =>
      init.method === "POST"
        ? reply({ code, message: "fixed" }, 503)
        : reply(empty),
    );
    vi.stubGlobal("fetch", fetcher);
    const props = await pageProps();
    const view = render(<ProfilesPage {...props} />);
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "New scenario" }),
      ).toBeEnabled(),
    );
    fireEvent.click(screen.getByRole("button", { name: "New scenario" }));
    fillForm("en");
    fireEvent.click(screen.getByRole("button", { name: "Save scenario" }));
    await screen.findByRole("button", { name: "Retry acknowledgement read" });
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    view.rerender(
      <ProfilesPage {...props} locale="ko" data={{ ...props.data }} />,
    );
    expect(screen.getByText(storageNotices.ko)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "새 시나리오" })).toBeDisabled();
    expect(fetcher.mock.calls.map(([, init]) => init.method)).toEqual([
      "GET",
      "POST",
    ]);
    view.unmount();
    render(<ProfilesPage {...props} />);
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "New scenario" }),
      ).toBeEnabled(),
    );
    expect(screen.queryByText(storageNotices.en)).not.toBeInTheDocument();
    expect(fetcher.mock.calls.map(([, init]) => init.method)).toEqual([
      "GET",
      "POST",
      "GET",
    ]);
    // A remount is not storage recovery: the same API denial is still honored.
    fireEvent.click(screen.getByRole("button", { name: "New scenario" }));
    fillForm("en");
    fireEvent.click(screen.getByRole("button", { name: "Save scenario" }));
    await screen.findByRole("button", { name: "Retry acknowledgement read" });
    expect(
      within(screen.getByRole("dialog")).getByText(storageNotices.en),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Save scenario" }),
    ).toBeDisabled();
    expect(fetcher.mock.calls.map(([, init]) => init.method)).toEqual([
      "GET",
      "POST",
      "GET",
      "POST",
    ]);
  },
);
it("keeps valid history, read reload and pagination reachable after closing a storage-failed draft", async () => {
  const records = await Promise.all(
    Array.from({ length: 51 }, (_, i) =>
      recordFixture(1, {
        id: `${String(i).padStart(8, "0")}-1111-4111-8111-111111111111`,
      }),
    ),
  );
  const fetcher = vi.fn(async (url: string, init: RequestInit) => {
    if (init.method === "POST")
      return reply(
        { code: "SCENARIO_STATE_UNAVAILABLE", message: "fixed" },
        503,
      );
    if (!url.includes("?")) {
      const record = records.find((item) => url.endsWith(item.id))!;
      return reply({
        revision: 51,
        scenario_id: record.id,
        versions: [record],
        execution_enabled: false,
      });
    }
    const offset = Number(
      new URL(url, "http://test.invalid").searchParams.get("offset"),
    );
    return reply({
      ...empty,
      revision: 51,
      total: 51,
      offset,
      items: records.slice(offset, offset + 50),
    });
  });
  vi.stubGlobal("fetch", fetcher);
  render(<ProfilesPage {...await pageProps()} />);
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "New scenario" })).toBeEnabled(),
  );
  fireEvent.click(screen.getByRole("button", { name: "New scenario" }));
  fillForm("en");
  fireEvent.click(screen.getByRole("button", { name: "Save scenario" }));
  await screen.findByRole("button", { name: "Retry acknowledgement read" });
  fireEvent.click(screen.getByRole("button", { name: "Close" }));
  expect(
    screen.getByRole("button", { name: "Reload scenarios" }),
  ).toBeEnabled();
  expect(
    screen.getAllByRole("button", { name: "Scenario history" }),
  ).toHaveLength(50);
  fireEvent.click(screen.getByRole("button", { name: "Reload scenarios" }));
  await waitFor(() =>
    expect(
      screen.getAllByRole("button", { name: "Scenario history" }),
    ).toHaveLength(50),
  );
  fireEvent.click(screen.getByRole("button", { name: "Next page" }));
  await waitFor(() =>
    expect(
      screen.getAllByRole("button", { name: "Scenario history" }),
    ).toHaveLength(1),
  );
  expect(screen.getByText(records[50].id)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Scenario history" }));
  await screen.findByLabelText("Revision");
  expect(
    within(screen.getByRole("dialog")).getByText(records[50].digest),
  ).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Edit scenario" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Close" }));
  fireEvent.click(screen.getByRole("button", { name: "Previous page" }));
  await waitFor(() =>
    expect(
      screen.getAllByRole("button", { name: "Scenario history" }),
    ).toHaveLength(50),
  );
  fireEvent.click(
    screen.getByRole("button", { name: "Review preserved draft" }),
  );
  expect(screen.getByLabelText("Scenario name")).toHaveValue(" Policy 🧪 ");
  expect(screen.getByLabelText("Scenario name")).toHaveAttribute("readonly");
  expect(screen.getByRole("button", { name: "Save scenario" })).toBeDisabled();
  expect(fetcher.mock.calls.map(([, init]) => init.method)).toEqual([
    "GET",
    "POST",
    "GET",
    "GET",
    "GET",
    "GET",
  ]);
});
it("retains the receipt after readback failure and GET-only retry accepts it behind a concurrent append", async () => {
  const one = await recordFixture(),
    two = await recordFixture(2, {
      definition: {
        ...(await recordFixture()).definition,
        name: "concurrent append",
      },
    });
  let saved = false,
    histories = 0;
  const fetcher = vi.fn(async (url: string, init: RequestInit) => {
    if (init.method === "POST") {
      saved = true;
      return reply(
        { revision: 1, scenario: one, execution_enabled: false },
        201,
      );
    }
    if (url.includes("?"))
      return reply(
        saved ? { ...empty, revision: 2, total: 1, items: [two] } : empty,
      );
    if (++histories === 1) throw new Error("read failed");
    return reply({
      revision: 2,
      scenario_id: one.id,
      versions: [one, two],
      execution_enabled: false,
    });
  });
  vi.stubGlobal("fetch", fetcher);
  render(<ProfilesPage {...await pageProps()} />);
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "New scenario" })).toBeEnabled(),
  );
  fireEvent.click(screen.getByRole("button", { name: "New scenario" }));
  fillForm("en");
  fireEvent.click(screen.getByRole("button", { name: "Save scenario" }));
  fireEvent.click(
    await screen.findByRole("button", { name: "Retry acknowledgement read" }),
  );
  expect(
    await screen.findByText(
      "Scenario saved and verified in immutable history. No execution was started.",
    ),
  ).toBeInTheDocument();
  expect(fetcher.mock.calls.map(([, init]) => init.method)).toEqual([
    "GET",
    "POST",
    "GET",
    "GET",
    "GET",
  ]);
  expect(
    screen.getByRole("heading", { name: "concurrent append" }),
  ).toBeInTheDocument();
});
it("permits pending close, prevents duplicate submission and never steals focus on late settlement", async () => {
  const one = await recordFixture();
  let resolve!: (v: Response) => void,
    saved = false;
  const fetcher = vi.fn(async (url: string, init: RequestInit) => {
    if (init.method === "POST") {
      saved = true;
      return new Promise<Response>((r) => {
        resolve = r;
      });
    }
    if (url.includes("?"))
      return reply(
        saved ? { ...empty, revision: 1, total: 1, items: [one] } : empty,
      );
    return reply({
      revision: 1,
      scenario_id: one.id,
      versions: [one],
      execution_enabled: false,
    });
  });
  vi.stubGlobal("fetch", fetcher);
  render(<ProfilesPage {...await pageProps()} />);
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "New scenario" })).toBeEnabled(),
  );
  fireEvent.click(screen.getByRole("button", { name: "New scenario" }));
  fillForm("en");
  const save = screen.getByRole("button", { name: "Save scenario" });
  fireEvent.click(save);
  fireEvent.click(save);
  expect(
    fetcher.mock.calls.filter(([, init]) => init.method === "POST"),
  ).toHaveLength(1);
  fireEvent.click(screen.getByRole("button", { name: "Close" }));
  const newerFocus = screen.getByRole("button", {
    name: "View details: Packet replay policy check",
  });
  newerFocus.focus();
  await act(async () =>
    resolve(
      reply({ revision: 1, scenario: one, execution_enabled: false }, 201),
    ),
  );
  await screen.findByText(
    "Scenario saved and verified in immutable history. No execution was started.",
  );
  expect(newerFocus).toHaveFocus();
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});
it("fails closed on history older than a known page and keeps retry explicit", async () => {
  const one = await recordFixture(),
    two = await recordFixture(2);
  let histories = 0;
  const fetcher = vi.fn(async (url: string) =>
    url.includes("?")
      ? reply({ ...empty, revision: 2, total: 1, items: [two] })
      : reply({
          revision: ++histories === 1 ? 1 : 2,
          scenario_id: one.id,
          versions: histories === 1 ? [one] : [one, two],
          execution_enabled: false,
        }),
  );
  vi.stubGlobal("fetch", fetcher);
  render(<ProfilesPage {...await pageProps()} />);
  fireEvent.click(
    await screen.findByRole("button", { name: "Scenario history" }),
  );
  expect(
    await screen.findByRole("button", { name: "Retry history read" }),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Edit scenario" }),
  ).not.toBeInTheDocument();
  expect(fetcher).toHaveBeenCalledTimes(2);
  fireEvent.click(screen.getByRole("button", { name: "Retry history read" }));
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Edit scenario" })).toBeEnabled(),
  );
});
it.each(["en", "ko"] as const)(
  "submits explicitly declared PCAP, detection and optional resource controls in %s",
  async (locale) => {
    let record: Awaited<ReturnType<typeof recordFixture>> | undefined;
    const fetcher = vi.fn(async (url: string, init: RequestInit) => {
      if (init.method === "POST") {
        record = await recordFixture(1, {
          definition: JSON.parse(init.body as string).definition,
        });
        return reply(
          { revision: 1, scenario: record, execution_enabled: false },
          201,
        );
      }
      return reply(
        url.includes("?")
          ? record
            ? { ...empty, revision: 1, total: 1, items: [record] }
            : empty
          : {
              revision: 1,
              scenario_id: record!.id,
              versions: [record],
              execution_enabled: false,
            },
      );
    });
    vi.stubGlobal("fetch", fetcher);
    render(<ProfilesPage {...await pageProps(locale)} />);
    const newButton = screen.getByRole("button", {
      name: locale === "en" ? "New scenario" : "새 시나리오",
    });
    await waitFor(() => expect(newButton).toBeEnabled());
    fireEvent.click(newButton);
    fillForm(locale);
    const fields =
      locale === "en"
        ? [
            "PCAP label",
            "PCAP SHA256",
            "PCAP size (bytes)",
            "Detection deadline (ms)",
            "Maximum CPU (%)",
            "Maximum memory (%)",
            "Maximum sessions",
          ]
        : [
            "PCAP 이름",
            "PCAP SHA256",
            "PCAP 크기(바이트)",
            "탐지 제한 시간(ms)",
            "최대 CPU 사용률(%)",
            "최대 메모리 사용률(%)",
            "최대 세션 수",
          ];
    fireEvent.click(
      screen.getByLabelText(
        locale === "en" ? "Declare PCAP identity" : "PCAP 식별 정보 선언",
      ),
    );
    fields.forEach((field, i) =>
      fireEvent.change(screen.getByLabelText(field), {
        target: {
          value: [
            " declared 🧪 ",
            "a".repeat(64),
            "4096",
            "500",
            "80",
            "70",
            "10",
          ][i],
        },
      }),
    );
    fireEvent.click(
      screen.getByLabelText(
        locale === "en" ? "Detection required" : "탐지 필수",
      ),
    );
    fireEvent.change(
      screen.getByLabelText(locale === "en" ? "Expected action" : "기대 동작"),
      { target: { value: "ALERT" } },
    );
    for (const role of locale === "en"
      ? ["DUT events", "Resource metrics"]
      : ["DUT 이벤트", "자원 메트릭"])
      fireEvent.click(screen.getByLabelText(role));
    expect(
      screen.getByLabelText(
        locale === "en" ? "Stop on management loss" : "관리 연결 손실 시 중지",
      ),
    ).toBeChecked();
    expect(
      screen.getByLabelText(
        locale === "en" ? "Stop on management loss" : "관리 연결 손실 시 중지",
      ),
    ).toBeDisabled();
    fireEvent.click(
      screen.getByRole("button", {
        name: locale === "en" ? "Save scenario" : "시나리오 저장",
      }),
    );
    await waitFor(() => expect(newButton).toBeEnabled());
    expect(record!.definition.pcap_asset).toEqual({
      label: " declared 🧪 ",
      sha256: "a".repeat(64),
      size_bytes: 4096,
    });
    expect(record!.definition.success_criteria.detection_deadline_ms).toBe(500);
    expect(record!.definition.stop_conditions).toMatchObject({
      max_cpu_pct: 80,
      max_memory_pct: 70,
      max_sessions: 10,
      management_loss: true,
    });
  },
);
it.each(storageFailures)(
  "never reopens or steals focus after pending-close %s and retains the literal draft",
  async (code) => {
    let finish!: (response: Response) => void;
    vi.stubGlobal(
      "fetch",
      vi.fn((_url: string, init: RequestInit) =>
        init.method === "POST"
          ? new Promise<Response>((r) => {
              finish = r;
            })
          : Promise.resolve(reply(empty)),
      ),
    );
    render(<ProfilesPage {...await pageProps()} />);
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "New scenario" }),
      ).toBeEnabled(),
    );
    fireEvent.click(screen.getByRole("button", { name: "New scenario" }));
    fillForm("en");
    fireEvent.click(screen.getByRole("button", { name: "Save scenario" }));
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    const focus = screen.getByRole("button", {
      name: "View details: Packet replay policy check",
    });
    focus.focus();
    await act(async () => finish(reply({ code, message: "fixed" }, 503)));
    expect(focus).toHaveFocus();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByText(storageNotices.en)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "New scenario" })).toBeDisabled();
    fireEvent.click(
      screen.getByRole("button", { name: "Review preserved draft" }),
    );
    expect(screen.getByLabelText("Scenario name")).toHaveValue(" Policy 🧪 ");
    expect(screen.getByLabelText("Scenario name")).toHaveAttribute("readonly");
  },
);
it.each(storageFailures)(
  "ignores late %s settlement from an unmounted library",
  async (code) => {
    let finish!: (response: Response) => void;
    const fetcher = vi.fn((_url: string, init: RequestInit) =>
      init.method === "POST"
        ? new Promise<Response>((resolve) => {
            finish = resolve;
          })
        : Promise.resolve(reply(empty)),
    );
    vi.stubGlobal("fetch", fetcher);
    const props = await pageProps();
    const view = render(<ProfilesPage {...props} />);
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "New scenario" }),
      ).toBeEnabled(),
    );
    fireEvent.click(screen.getByRole("button", { name: "New scenario" }));
    fillForm("en");
    fireEvent.click(screen.getByRole("button", { name: "Save scenario" }));
    const signal = fetcher.mock.calls.find(
      ([, init]) => init.method === "POST",
    )![1].signal!;
    view.unmount();
    expect(signal.aborted).toBe(true);
    render(<ProfilesPage {...props} />);
    const create = screen.getByRole("button", { name: "New scenario" });
    await waitFor(() => expect(create).toBeEnabled());
    create.focus();
    await act(async () => finish(reply({ code, message: "fixed" }, 503)));
    expect(create).toBeEnabled();
    expect(create).toHaveFocus();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.queryByText(storageNotices.en)).not.toBeInTheDocument();
    expect(fetcher.mock.calls.map(([, init]) => init.method)).toEqual([
      "GET",
      "POST",
      "GET",
    ]);
  },
);
it("retains a PUT opening revision through conflict and refresh, and only an explicit discard opens the latest revision", async () => {
  const one = await recordFixture(),
    two = await recordFixture(2, {
      definition: {
        ...(await recordFixture()).definition,
        name: "newer stored name",
      },
    });
  let conflict = false;
  const fetcher = vi.fn(async (url: string, init: RequestInit) => {
    if (init.method === "PUT") {
      expect(JSON.parse(init.body as string).revision).toBe(1);
      conflict = true;
      return reply({ code: "SCENARIO_CONFLICT", message: "fixed" }, 409);
    }
    return reply(
      url.includes("?")
        ? {
            ...empty,
            revision: conflict ? 2 : 1,
            total: 1,
            items: [conflict ? two : one],
          }
        : {
            revision: conflict ? 2 : 1,
            scenario_id: one.id,
            versions: conflict ? [one, two] : [one],
            execution_enabled: false,
          },
    );
  });
  vi.stubGlobal("fetch", fetcher);
  render(<ProfilesPage {...await pageProps()} />);
  fireEvent.click(
    await screen.findByRole("button", { name: "Scenario history" }),
  );
  fireEvent.click(await screen.findByRole("button", { name: "Edit scenario" }));
  fireEvent.change(screen.getByLabelText("Scenario name"), {
    target: { value: "unsaved intent" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save new version" }));
  fireEvent.click(
    await screen.findByRole("button", { name: "Retry acknowledgement read" }),
  );
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "Discard draft and reopen" }),
    ).toBeEnabled(),
  );
  expect(screen.getByText("Opening registry revision: 1")).toBeInTheDocument();
  expect(screen.getByLabelText("Scenario name")).toHaveValue("unsaved intent");
  fireEvent.click(
    screen.getByRole("button", { name: "Discard draft and reopen" }),
  );
  await waitFor(() =>
    expect(screen.getByLabelText("Scenario name")).toHaveValue(
      "newer stored name",
    ),
  );
  expect(screen.getByText("Opening registry revision: 2")).toBeInTheDocument();
  expect(
    fetcher.mock.calls.filter(([, init]) => init.method === "PUT"),
  ).toHaveLength(1);
});
it("rejects missing budgets and inconsistent protocol/action/evidence locally without a write", async () => {
  const fetcher = vi.fn().mockResolvedValue(reply(empty));
  vi.stubGlobal("fetch", fetcher);
  render(<ProfilesPage {...await pageProps()} />);
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "New scenario" })).toBeEnabled(),
  );
  fireEvent.click(screen.getByRole("button", { name: "New scenario" }));
  fireEvent.click(screen.getByRole("button", { name: "Save scenario" }));
  expect(screen.getByRole("alert")).toHaveTextContent(
    "Check all required fields",
  );
  fillForm("en");
  fireEvent.change(screen.getByLabelText("Expected action"), {
    target: { value: "ALERT" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save scenario" }));
  expect(screen.getByRole("alert")).toHaveTextContent(
    "Check all required fields",
  );
  expect(fetcher).toHaveBeenCalledTimes(1);
});
