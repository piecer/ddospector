import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Locale, Target } from "../../lib/contracts";
import { label } from "../scenarios/labels";
import { recordFixture } from "../scenarios/testRecords";
import { definitionFixture } from "../scenarios/testFixtures";
import type {
  ScenarioInputDraft,
  ScenarioInputResult,
} from "./scenario-grant-inputs";

const modules = import.meta.glob("./ScenarioGrantInputs.tsx", { eager: true });
const module = modules[
  "./ScenarioGrantInputs.tsx"
] as typeof import("./ScenarioGrantInputs");
const targets: Target[] = [
  {
    id: "dut-test",
    name: " <b>DUT</b> ",
    address: "lab.test",
    kind: "DUT",
    status: "draft",
    created_at: "2026-10-09T00:00:00+00:00",
  },
  {
    id: "sink-test",
    name: " Sink ",
    address: "::1",
    kind: "SINK",
    status: "draft",
    created_at: "2026-10-09T00:00:00+00:00",
  },
];
const requiredValues = {
  dut_version: " firmware 🧪 ",
  policy_version: " policy ",
  max_pps: "1",
  max_bps: "2",
  max_packets: "3",
  max_bytes: "4",
  max_connections: "5",
  duration_seconds: "6",
  max_legitimate_loss_pct: "0",
  max_service_latency_ms: "7",
};

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("ScenarioGrantInputs operator form", () => {
  it("has no transport/persistence side effects and preserves invalid numeric text across locale rerenders", async () => {
    const fetcher = vi.fn(() => {
      throw Error("network forbidden");
    });
    vi.stubGlobal("fetch", fetcher);
    const storageWrite = vi.spyOn(Storage.prototype, "setItem");
    const Component = module.ScenarioGrantInputs;
    const onChange =
      vi.fn<(result: ScenarioInputResult, draft: ScenarioInputDraft) => void>();
    const user = userEvent.setup();
    const { rerender } = render(
      <Component lang="en" targets={[]} disabled={false} onChange={onChange} />,
    );
    await user.type(
      screen.getByRole("textbox", { name: "Maximum PPS" }),
      "1e2",
    );
    expect(onChange).toHaveBeenCalledTimes(3);
    expect(screen.getByRole("textbox", { name: "Maximum PPS" })).toHaveValue(
      "1e2",
    );
    expect(onChange.mock.lastCall![0]).toMatchObject({
      valid: false,
      errors: expect.arrayContaining(["target_id", "sink_id", "max_pps"]),
    });
    expect(
      screen.getByRole("textbox", { name: "Maximum PPS" }),
    ).toHaveAttribute("aria-invalid", "true");
    rerender(
      <Component
        lang="ko"
        targets={targets}
        disabled={false}
        onChange={onChange}
      />,
    );
    expect(screen.getByRole("textbox", { name: "최대 PPS" })).toHaveValue(
      "1e2",
    );
    expect(onChange).toHaveBeenCalledTimes(3);
    await user.selectOptions(
      screen.getByRole("combobox", { name: "입력 출처" }),
      "scenario_version",
    );
    expect(
      screen.getByRole("button", { name: "선택한 버전 사용" }),
    ).toBeDisabled();
    expect(
      screen.queryByRole("button", { name: "운영자 입력으로 복사" }),
    ).not.toBeInTheDocument();
    expect(onChange.mock.lastCall![0]).toEqual({
      valid: false,
      errors: ["source"],
    });
    expect(fetcher).not.toHaveBeenCalled();
    expect(storageWrite).not.toHaveBeenCalled();
  });

  it.each(["en", "ko"] as Locale[])(
    "captures only explicitly chosen versions and copies to edit in %s",
    async (lang) => {
      const Component = module.ScenarioGrantInputs;
      const definition = definitionFixture();
      const record = await recordFixture(2, {
        id: "legacy-scenario",
        definition: {
          ...definition,
          dut_version: " <script>declared</script> ",
          stop_conditions: {
            ...definition.stop_conditions,
            max_legitimate_loss_pct: 0,
          },
        },
      });
      const before = structuredClone(record);
      const onChange =
        vi.fn<
          (result: ScenarioInputResult, draft: ScenarioInputDraft) => void
        >();
      const onRequestVersion = vi.fn();
      const user = userEvent.setup();
      const props = {
        lang,
        targets,
        disabled: false,
        selectedVersion: record,
        onChange,
        onRequestVersion,
      };
      const { rerender, container } = render(<Component {...props} />);
      expect(
        screen.getByRole("textbox", { name: label(lang, "max_pps") }),
      ).toHaveValue("");
      const source = () =>
        screen.getByRole("combobox", {
          name: lang === "en" ? "Input source" : "입력 출처",
        });
      await user.selectOptions(source(), "scenario_version");
      expect(onChange.mock.lastCall![0]).toEqual({
        valid: false,
        errors: ["source"],
      });
      await user.click(
        screen.getByRole("button", {
          name: lang === "en" ? "Choose another version" : "다른 버전 선택",
        }),
      );
      expect(onRequestVersion).toHaveBeenCalledTimes(1);
      const apply = () =>
        screen.getByRole("button", {
          name: lang === "en" ? "Use selected version" : "선택한 버전 사용",
        });
      await user.click(apply());
      expect(onChange.mock.lastCall![0]).toEqual({
        valid: true,
        input_source: {
          source: "scenario_version",
          reference: { id: record.id, version: 2, digest: record.digest },
        },
        resolved_inputs: expect.objectContaining({
          dut_version: " <script>declared</script> ",
          stop_conditions: record.definition.stop_conditions,
        }),
      });
      expect(
        screen.getByRole("textbox", { name: label(lang, "max_pps") }),
      ).toHaveValue("100");
      expect(
        screen.getByRole("textbox", { name: label(lang, "max_cpu_pct") }),
      ).toHaveValue("null");
      expect(
        screen.getByRole("textbox", { name: label(lang, "max_memory_pct") }),
      ).toHaveValue("null");
      expect(
        screen.getByRole("textbox", { name: label(lang, "max_sessions") }),
      ).toHaveValue("null");
      expect(
        screen.getByRole("textbox", { name: label(lang, "target_id") }),
      ).toHaveValue("dut-test");
      expect(
        screen.getByRole("textbox", { name: label(lang, "dut_version") }),
      ).toHaveValue(" <script>declared</script> ");
      expect(container.querySelector("script")).toBeNull();
      expect(screen.getByText(record.digest)).toBeVisible();
      expect(
        screen.getByText("legacy-scenario", { selector: "dd" }),
      ).toBeVisible();
      const calls = onChange.mock.calls.length;
      const emitted = onChange.mock.lastCall![1];
      const emittedResult = onChange.mock.lastCall![0];
      if (
        emitted.source !== "scenario_version" ||
        !emitted.selection ||
        !emittedResult.valid
      )
        throw Error("expected captured source");
      emitted.selection.inputs.traffic_budget.max_pps = 888;
      emitted.selection.reference.id = "changed-callback";
      emittedResult.resolved_inputs.dut_version = "changed-callback";
      await user.type(
        screen.getByRole("textbox", { name: label(lang, "max_pps") }),
        "9",
      );
      expect(onChange).toHaveBeenCalledTimes(calls);
      expect(record).toEqual(before);
      // Even alias mutation + a later prop version cannot silently change capture.
      record.definition.traffic_budget.max_pps = 777;
      const newer = await recordFixture(3, { id: "newer-scenario" });
      rerender(<Component {...props} selectedVersion={newer} />);
      expect(onChange).toHaveBeenCalledTimes(calls);
      expect(
        screen.getByRole("textbox", { name: label(lang, "max_pps") }),
      ).toHaveValue("100");
      expect(
        screen.getByText("legacy-scenario", { selector: "dd" }),
      ).toBeVisible();
      await user.click(
        screen.getByRole("button", {
          name:
            lang === "en" ? "Copy to operator inputs" : "운영자 입력으로 복사",
        }),
      );
      expect(source()).toHaveValue("operator");
      expect(onChange.mock.lastCall![0]).toMatchObject({
        valid: true,
        input_source: {
          source: "operator",
          inputs: { traffic_budget: { max_pps: 100 } },
        },
      });
      expect(onChange.mock.lastCall![1]).not.toHaveProperty("selection");
      await user.clear(
        screen.getByRole("textbox", { name: label(lang, "max_pps") }),
      );
      expect(onChange.mock.lastCall![0]).toEqual({
        valid: false,
        errors: ["max_pps"],
      });
      await user.selectOptions(source(), "scenario_version");
      expect(onChange.mock.lastCall![0].valid).toBe(false);
      await user.click(apply());
      expect(onChange.mock.lastCall![0]).toMatchObject({
        valid: true,
        input_source: {
          source: "scenario_version",
          reference: { id: "newer-scenario", version: 3 },
        },
      });
      // Mode switching is NOT an implicit copy operation.
      await user.selectOptions(source(), "operator");
      expect(
        screen.getByRole("textbox", { name: label(lang, "max_pps") }),
      ).toHaveValue("");
      expect(onChange.mock.lastCall![0].valid).toBe(false);
    },
  );
  it("locks operator, mode, selection, copy and reset controls while disabled", async () => {
    const Component = module.ScenarioGrantInputs;
    const user = userEvent.setup();
    const onChange = vi.fn();
    const onReset = vi.fn();
    const onRequestVersion = vi.fn();
    const record = await recordFixture();
    const props = {
      lang: "en" as const,
      disabled: false,
      targets,
      selectedVersion: record,
      onChange,
      onReset,
      onRequestVersion,
    };
    const { rerender, container } = render(<Component {...props} />);
    await user.type(screen.getByRole("textbox", { name: "Maximum PPS" }), "12");
    await user.click(
      screen.getByRole("checkbox", { name: "Declare PCAP identity" }),
    );
    rerender(<Component {...props} disabled />);
    for (const control of container.querySelectorAll("input, select, button"))
      expect(control).toBeDisabled();
    const count = onChange.mock.calls.length;
    await user.type(screen.getByRole("textbox", { name: "Maximum PPS" }), "3");
    await user.click(screen.getByRole("button", { name: "Reset inputs" }));
    expect(onChange).toHaveBeenCalledTimes(count);
    expect(onReset).not.toHaveBeenCalled();
    expect(screen.getByRole("textbox", { name: "Maximum PPS" })).toHaveValue(
      "12",
    );
    rerender(<Component {...props} />);
    await user.selectOptions(
      screen.getByRole("combobox", { name: "Input source" }),
      "scenario_version",
    );
    await user.click(
      screen.getByRole("button", { name: "Use selected version" }),
    );
    rerender(<Component {...props} disabled />);
    for (const control of container.querySelectorAll("input, select, button"))
      expect(control).toBeDisabled();
    const capturedCount = onChange.mock.calls.length;
    for (const name of [
      "Copy to operator inputs",
      "Choose another version",
      "Use selected version",
      "Reset inputs",
    ])
      await user.click(screen.getByRole("button", { name }));
    expect(onChange).toHaveBeenCalledTimes(capturedCount);
    expect(onRequestVersion).not.toHaveBeenCalled();
    expect(onReset).not.toHaveBeenCalled();
  });

  it.each(["en", "ko"] as Locale[])(
    "collects explicit protected inputs and reset callbacks in %s",
    async (lang) => {
      expect(
        module?.ScenarioGrantInputs,
        "operator-owned scenario input panel",
      ).toBeTypeOf("function");
      const Component = module.ScenarioGrantInputs;
      const onChange =
        vi.fn<
          (result: ScenarioInputResult, draft: ScenarioInputDraft) => void
        >();
      const onReset = vi.fn();
      const user = userEvent.setup();
      const { container } = render(
        <Component
          lang={lang}
          targets={targets}
          disabled={false}
          onChange={onChange}
          onReset={onReset}
        />,
      );
      expect(onChange).not.toHaveBeenCalled();
      for (const key of Object.keys(
        requiredValues,
      ) as (keyof typeof requiredValues)[])
        expect(
          screen.getByRole("textbox", { name: label(lang, key) }),
        ).toHaveValue("");
      expect(
        screen.getByRole("combobox", { name: label(lang, "target_id") }),
      ).toHaveValue("");
      expect(
        screen.getByRole("combobox", { name: label(lang, "sink_id") }),
      ).toHaveValue("");
      expect(
        screen.getByText(
          lang === "en" ? /Execution disabled/ : /실행 비활성화/,
        ),
      ).toBeVisible();
      expect(
        screen.getByText(
          lang === "en" ? /not measurements/ : /측정 결과가 아닙니다/,
        ),
      ).toBeVisible();
      expect(screen.queryByText(/^Saved$/)).not.toBeInTheDocument();
      expect(
        container.querySelector('input[type="file"], input[type="url"], b'),
      ).toBeNull();
      await user.selectOptions(
        screen.getByRole("combobox", { name: label(lang, "target_id") }),
        "dut-test",
      );
      expect(onChange).toHaveBeenCalledTimes(1);
      expect(onChange.mock.lastCall?.[0].valid).toBe(false);
      await user.selectOptions(
        screen.getByRole("combobox", { name: label(lang, "sink_id") }),
        "sink-test",
      );
      for (const [key, value] of Object.entries(requiredValues)) {
        const before = onChange.mock.calls.length;
        await user.type(
          screen.getByRole("textbox", {
            name: label(lang, key as keyof typeof requiredValues),
          }),
          value,
        );
        expect(onChange.mock.calls.length).toBeGreaterThan(before);
      }
      const result = onChange.mock.lastCall![0];
      expect(result).toMatchObject({
        valid: true,
        input_source: { source: "operator" },
        resolved_inputs: {
          target_id: "dut-test",
          sink_id: "sink-test",
          dut_version: " firmware 🧪 ",
          policy_version: " policy ",
          pcap_asset: null,
          traffic_budget: {
            max_pps: 1,
            max_bps: 2,
            max_packets: 3,
            max_bytes: 4,
            max_connections: 5,
            duration_seconds: 6,
          },
          stop_conditions: {
            max_legitimate_loss_pct: 0,
            max_service_latency_ms: 7,
            max_cpu_pct: null,
            max_memory_pct: null,
            max_sessions: null,
            management_loss: true,
          },
        },
      });
      expect(
        screen.getByRole("checkbox", { name: label(lang, "management_loss") }),
      ).toBeChecked();
      expect(
        screen.getByRole("checkbox", { name: label(lang, "management_loss") }),
      ).toBeDisabled();
      // Callback consumers cannot mutate transient state or its other emitted values.
      const emittedDraft = onChange.mock.lastCall![1];
      if (emittedDraft.source !== "operator" || !result.valid)
        throw Error("expected operator");
      emittedDraft.values.max_pps = "999";
      result.resolved_inputs.traffic_budget.max_pps = 998;
      await user.type(
        screen.getByRole("textbox", { name: label(lang, "max_cpu_pct") }),
        "8",
      );
      expect(onChange.mock.lastCall![0]).toMatchObject({
        valid: true,
        resolved_inputs: {
          traffic_budget: { max_pps: 1 },
          stop_conditions: { max_cpu_pct: 8 },
        },
      });
      await user.clear(
        screen.getByRole("textbox", { name: label(lang, "max_cpu_pct") }),
      );
      expect(onChange.mock.lastCall![0]).toMatchObject({
        valid: true,
        resolved_inputs: { stop_conditions: { max_cpu_pct: null } },
      });
      await user.click(
        screen.getByRole("checkbox", { name: label(lang, "pcap_declared") }),
      );
      expect(onChange.mock.lastCall![0].valid).toBe(false);
      await user.type(
        screen.getByRole("textbox", { name: label(lang, "asset_label") }),
        " <i>asset</i> ",
      );
      await user.type(
        screen.getByRole("textbox", { name: label(lang, "asset_sha256") }),
        "a".repeat(64),
      );
      await user.type(
        screen.getByRole("textbox", { name: label(lang, "asset_size_bytes") }),
        "1",
      );
      expect(onChange.mock.lastCall![0]).toMatchObject({
        valid: true,
        resolved_inputs: {
          pcap_asset: {
            label: " <i>asset</i> ",
            sha256: "a".repeat(64),
            size_bytes: 1,
          },
        },
      });
      expect(container.querySelector("i")).toBeNull();
      await user.click(
        screen.getByRole("checkbox", { name: label(lang, "pcap_declared") }),
      );
      expect(onChange.mock.lastCall![0]).toMatchObject({
        valid: true,
        resolved_inputs: { pcap_asset: null },
      });
      await user.click(
        screen.getByRole("button", {
          name: lang === "en" ? "Reset inputs" : "입력 초기화",
        }),
      );
      expect(onReset).toHaveBeenCalledTimes(1);
      expect(onChange.mock.lastCall![0].valid).toBe(false);
      for (const key of Object.keys(
        requiredValues,
      ) as (keyof typeof requiredValues)[])
        expect(
          screen.getByRole("textbox", { name: label(lang, key) }),
        ).toHaveValue("");
    },
  );
});
