import { useState } from "react";
import type { Locale, Target } from "../../lib/contracts";
import { Button, Field, Notice } from "../../components/ui";
import { choose } from "../../lib/i18n";
import { label } from "../scenarios/labels";
import { budgetBounds } from "../scenarios/validation";
import {
  buildScenarioInputResult,
  newScenarioInputDraft,
  scenarioInputDraftFromVersion,
  copyScenarioInputsToOperator,
} from "./scenario-grant-inputs";
import type { ScenarioVersion } from "../scenarios/types";
import type {
  ScenarioInputDraft,
  ScenarioInputResult,
  ScenarioInputValues,
} from "./scenario-grant-inputs";
import "../scenarios/scenarios.css";

export type ScenarioGrantInputsProps = {
  lang: Locale;
  disabled: boolean;
  targets: readonly Target[];
  /** Every operator edit, including invalid/blank edits. Clear unused consent here. */
  onChange: (result: ScenarioInputResult, draft: ScenarioInputDraft) => void;
  onReset?: () => void;
  /** Offered selection only; never populates controls until explicit Use action.
   * Parent must supply a fully codec-validated immutable ScenarioVersion.
   */
  selectedVersion?: ScenarioVersion | null;
  /** Parent owns selection/fetch; this component clears captured selection first. */
  onRequestVersion?: () => void;
};

/** Transient operator inputs only. No grant, model, storage or transport access. */
export function ScenarioGrantInputs({
  lang,
  disabled,
  targets,
  selectedVersion,
  onChange,
  onReset,
  onRequestVersion,
}: ScenarioGrantInputsProps) {
  const c = (en: string, ko: string) => choose(lang, en, ko);
  const [draft, setDraft] = useState<ScenarioInputDraft>(newScenarioInputDraft);
  const result = buildScenarioInputResult(draft, targets);
  const readOnly = draft.source === "scenario_version";
  const view =
    draft.source === "operator" ? draft : copyScenarioInputsToOperator(draft);
  function change(next: ScenarioInputDraft) {
    if (disabled) return;
    setDraft(structuredClone(next));
    onChange(buildScenarioInputResult(next, targets), structuredClone(next));
  }
  const update = (key: keyof ScenarioInputValues, value: string) => {
    if (draft.source === "operator")
      change({ ...draft, values: { ...draft.values, [key]: value } });
  };
  const field = (
    key: keyof ScenarioInputValues,
    hint?: string,
    numeric = false,
  ) => (
    <Field key={key} label={label(lang, key)} hint={hint}>
      <input
        type="text"
        inputMode={numeric ? "numeric" : undefined}
        value={
          readOnly && view?.values[key] === ""
            ? "null"
            : (view?.values[key] ?? "")
        }
        readOnly={readOnly}
        aria-invalid={!result.valid && result.errors.includes(key)}
        onChange={(e) => update(key, e.target.value)}
      />
    </Field>
  );
  const numeric = (
    key: keyof ScenarioInputValues,
    min: number,
    max: number,
    nullable = false,
  ) =>
    field(
      key,
      nullable
        ? c(
            `Optional; blank = null (not configured). ASCII integer ${min}–${max}.`,
            `선택 사항. 빈칸 = null (미설정). ASCII 정수 ${min}~${max}.`,
          )
        : c(
            `Required ASCII integer ${min}–${max}.`,
            `필수 ASCII 정수 ${min}~${max}.`,
          ),
      true,
    );
  return (
    <fieldset disabled={disabled} className="scenario-fields form-stack">
      <legend>{c("Scenario inputs", "시나리오 입력")}</legend>
      <Notice tone="warning">
        {c(
          "Execution disabled. These are declarations, not measurements or verified device limits. No safe defaults or permission are supplied.",
          "실행 비활성화. 선언값이며 측정 결과가 아닙니다. 검증된 장비 한도, 안전한 기본값 또는 권한을 제공하지 않습니다.",
        )}
      </Notice>
      <Field
        label={c("Input source", "입력 출처")}
        hint={c(
          "Changing modes clears inputs. Use Copy to edit a captured version.",
          "모드 변경 시 입력이 초기화됩니다. 선택 버전을 편집하려면 복사하세요.",
        )}
      >
        <select
          value={draft.source}
          onChange={(e) =>
            change(
              e.target.value === "operator"
                ? newScenarioInputDraft()
                : { source: "scenario_version", selection: null },
            )
          }
        >
          <option value="operator">
            {c("Operator values", "운영자 입력값")}
          </option>
          <option value="scenario_version">
            {c("Selected immutable version", "선택한 불변 버전")}
          </option>
        </select>
      </Field>
      {draft.source === "scenario_version" && (
        <section className="form-stack">
          <h3>{c("Immutable source", "불변 출처")}</h3>
          <p>
            {c(
              "Historical declarations only; no latest-version substitution. Copying to edit changes provenance to operator.",
              "과거 선언값입니다. 최신 버전으로 대체하지 않습니다. 편집 복사 시 출처는 운영자 입력으로 변경됩니다.",
            )}
          </p>
          {selectedVersion ? (
            <p style={{ overflowWrap: "anywhere", whiteSpace: "pre-wrap" }}>
              {c("Offered selection: ", "제공된 선택: ")}
              {selectedVersion.id} · {selectedVersion.version} ·{" "}
              {selectedVersion.definition.name}
            </p>
          ) : (
            <p>
              {c(
                "No version selected. Ask the parent selector for an exact version.",
                "선택된 버전이 없습니다. 상위 선택기에서 정확한 버전을 선택하세요.",
              )}
            </p>
          )}
          {onRequestVersion && (
            <Button
              onClick={() => {
                if (disabled) return;
                change({ source: "scenario_version", selection: null });
                onRequestVersion();
              }}
            >
              {c("Choose another version", "다른 버전 선택")}
            </Button>
          )}
          <Button
            disabled={!selectedVersion}
            onClick={() => {
              if (selectedVersion)
                change(scenarioInputDraftFromVersion(selectedVersion));
            }}
          >
            {c("Use selected version", "선택한 버전 사용")}
          </Button>
          {draft.selection && (
            <>
              <dl style={{ overflowWrap: "anywhere" }}>
                <dt>{c("Captured scenario ID", "확정한 시나리오 ID")}</dt>
                <dd>{draft.selection.reference.id}</dd>
                <dt>{c("Captured version", "확정한 버전")}</dt>
                <dd>{draft.selection.reference.version}</dd>
                <dt>{c("Captured digest", "확정한 다이제스트")}</dt>
                <dd>{draft.selection.reference.digest}</dd>
              </dl>
              <Button
                onClick={() => {
                  const copied = copyScenarioInputsToOperator(draft);
                  if (copied) change(copied);
                }}
              >
                {c("Copy to operator inputs", "운영자 입력으로 복사")}
              </Button>
            </>
          )}
        </section>
      )}
      {view && (
        <>
          <section className="form-stack">
            <h3>{c("Declared identity", "선언된 식별 정보")}</h3>
            <div className="scenario-grid">
              {(["target_id", "sink_id"] as const).map((key) =>
                readOnly ? (
                  field(key)
                ) : (
                  <Field
                    key={key}
                    label={label(lang, key)}
                    hint={c(
                      "Registered draft, not verified hardware. Names are literal.",
                      "등록 초안은 검증된 장비가 아닙니다. 이름 원문을 유지합니다.",
                    )}
                  >
                    <select
                      value={view.values[key]}
                      aria-invalid={
                        !result.valid && result.errors.includes(key)
                      }
                      onChange={(e) => update(key, e.target.value)}
                    >
                      <option value="">
                        {c("Choose a target", "대상 선택")}
                      </option>
                      {view.values[key] &&
                        !targets.some(
                          (t) =>
                            t.id === view.values[key] &&
                            t.kind === (key === "target_id" ? "DUT" : "SINK"),
                        ) && (
                          <option value={view.values[key]}>
                            {c("Unavailable: ", "사용 불가: ")}
                            {view.values[key]}
                          </option>
                        )}
                      {targets
                        .filter(
                          (t) =>
                            t.kind === (key === "target_id" ? "DUT" : "SINK"),
                        )
                        .map((t) => (
                          <option key={t.id} value={t.id}>
                            {t.name} · {t.id}
                          </option>
                        ))}
                    </select>
                  </Field>
                ),
              )}
              {field(
                "dut_version",
                c(
                  "Required; 1–120 Unicode characters. Literal declared version.",
                  "필수 유니코드 1~120자. 선언된 버전 원문입니다.",
                ),
              )}
              {field(
                "policy_version",
                c(
                  "Required; 1–120 Unicode characters. Literal declared version.",
                  "필수 유니코드 1~120자. 선언된 버전 원문입니다.",
                ),
              )}
            </div>
          </section>
          <section className="form-stack">
            <h3>{c("Traffic budget", "트래픽 예산")}</h3>
            <p>
              {c(
                "Enter every budget. Ceilings are representational limits, not device-safe recommendations.",
                "모든 예산을 입력하세요. 상한은 표현 한도이며 장비 안전 권장값이 아닙니다.",
              )}
            </p>
            <div className="scenario-grid">
              {(Object.keys(budgetBounds) as (keyof typeof budgetBounds)[]).map(
                (key) => numeric(key, 1, budgetBounds[key]),
              )}
            </div>
          </section>
          <section className="form-stack">
            <h3>{c("Stop conditions", "중지 조건")}</h3>
            <div className="scenario-grid">
              {numeric("max_legitimate_loss_pct", 0, 100)}
              {numeric("max_service_latency_ms", 1, 60000)}
              {numeric("max_cpu_pct", 1, 100, true)}
              {numeric("max_memory_pct", 1, 100, true)}
              {numeric("max_sessions", 1, 1000000, true)}
              <Field
                label={label(lang, "management_loss")}
                hint={c(
                  "Mandatory existing policy: true. Cannot be disabled.",
                  "기존 필수 정책: true. 비활성화할 수 없습니다.",
                )}
              >
                <input type="checkbox" checked disabled />
              </Field>
            </div>
          </section>
          <section className="form-stack">
            <h3>{c("Declared PCAP identity", "선언된 PCAP 식별 정보")}</h3>
            <p>
              {c(
                "Metadata only. No file or URL is opened, read or verified.",
                "메타데이터 전용. 파일이나 URL을 열거나 읽거나 검증하지 않습니다.",
              )}
            </p>
            <Field label={label(lang, "pcap_declared")}>
              <input
                type="checkbox"
                checked={view.asset}
                disabled={readOnly}
                onChange={(e) => {
                  if (draft.source === "operator")
                    change({ ...draft, asset: e.target.checked });
                }}
              />
            </Field>
            {view.asset ? (
              <div className="scenario-grid">
                {field(
                  "asset_label",
                  c(
                    "Required literal label; 1–120 Unicode characters.",
                    "필수 이름 원문. 유니코드 1~120자.",
                  ),
                )}
                {field(
                  "asset_sha256",
                  c(
                    "Exactly 64 lowercase hexadecimal characters.",
                    "소문자 16진수 정확히 64자.",
                  ),
                )}
                {numeric("asset_size_bytes", 1, 67108864)}
              </div>
            ) : (
              <p>{c("PCAP: null (not declared)", "PCAP: null (미선언)")}</p>
            )}
          </section>
        </>
      )}
      <p role="status">
        {result.valid
          ? c(
              "Inputs complete; no authority granted or definition saved.",
              "입력 완료. 권한 부여 또는 정의 저장이 아닙니다.",
            )
          : c("Incomplete or invalid inputs: ", "불완전하거나 잘못된 입력: ") +
            result.errors
              .map((key) =>
                key === "source"
                  ? c("Input source", "입력 출처")
                  : label(lang, key),
              )
              .join(", ")}
      </p>
      <Button
        onClick={() => {
          if (disabled) return;
          change(newScenarioInputDraft());
          onReset?.();
        }}
      >
        {c("Reset inputs", "입력 초기화")}
      </Button>
    </fieldset>
  );
}
