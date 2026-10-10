import type { Locale, Target } from "../../lib/contracts";
import { Field, Notice } from "../../components/ui";
import { choose, text } from "../../lib/i18n";
import { scenarioProfiles } from "./catalog";
import { label } from "./labels";
import { budgetBounds } from "./validation";
import { evidenceRoles } from "./types";
import type { Draft, Values } from "./draft";
export function ScenarioFields({
  draft,
  change,
  targets,
  locale,
  locked,
}: {
  draft: Draft;
  change: (draft: Draft) => void;
  targets: Target[];
  locale: Locale;
  locked: boolean;
}) {
  const c = (en: string, ko: string) => choose(locale, en, ko);
  const v = draft.values;
  const update = (key: keyof Values, value: string) =>
    change({ ...draft, values: { ...v, [key]: value } });
  const textField = (key: keyof Values, multiline = false) => (
    <Field
      key={key}
      label={label(locale, key)}
      hint={
        key === "objective"
          ? c(
              "1–2000 Unicode characters; multiline text is preserved.",
              "유니코드 1~2000자. 여러 줄 원문을 보존합니다.",
            )
          : undefined
      }
    >
      {multiline ? (
        <textarea
          value={v[key]}
          rows={4}
          readOnly={locked}
          onChange={(e) => update(key, e.target.value)}
        />
      ) : (
        <input
          value={v[key]}
          readOnly={locked}
          onChange={(e) => update(key, e.target.value)}
        />
      )}
    </Field>
  );
  const numeric = (
    key: keyof Values,
    min: number,
    max: number,
    nullable = false,
  ) => (
    <Field
      key={key}
      label={label(locale, key)}
      hint={
        nullable
          ? c(
              `Optional; blank means not configured. Integer ${min}–${max}.`,
              `선택 사항. 비워 두면 미설정입니다. 정수 ${min}~${max}.`,
            )
          : c(`Required integer ${min}–${max}.`, `필수 정수 ${min}~${max}.`)
      }
    >
      <input
        type="number"
        inputMode="numeric"
        step={1}
        min={min}
        max={max}
        value={v[key]}
        readOnly={locked}
        onChange={(e) => update(key, e.target.value)}
      />
    </Field>
  );
  const select = (key: keyof Values, values: readonly string[]) => (
    <Field label={label(locale, key)}>
      <select
        value={v[key]}
        disabled={locked}
        onChange={(e) => update(key, e.target.value)}
      >
        {values.map((value) => (
          <option key={value} value={value}>
            {value === "ALLOW"
              ? c("Allow", "허용")
              : value === "BLOCK"
                ? c("Block", "차단")
                : value === "ALERT"
                  ? c("Alert", "경보")
                  : value}
          </option>
        ))}
      </select>
    </Field>
  );
  return (
    <div className="scenario-fields form-stack">
      <section>
        <h3>{c("Identity and intent", "식별 정보와 목적")}</h3>
        <div className="form-stack">
          {textField("name")}
          {textField("objective", true)}
          <div className="scenario-grid">
            {textField("dut_version")}
            {textField("policy_version")}
            {(["target_id", "sink_id"] as const).map((key) => (
              <Field
                key={key}
                label={label(locale, key)}
                hint={c(
                  "A registered draft is not verified hardware. Hostnames remain unresolved.",
                  "등록 초안은 검증된 장비가 아닙니다. 호스트 이름은 해석하지 않습니다.",
                )}
              >
                <select
                  value={v[key]}
                  disabled={locked}
                  onChange={(e) => update(key, e.target.value)}
                >
                  <option value="">{c("Choose a target", "대상 선택")}</option>
                  {v[key] &&
                    !targets.some(
                      (t) =>
                        t.id === v[key] &&
                        t.kind === (key === "target_id" ? "DUT" : "SINK"),
                    ) && (
                      <option value={v[key]}>
                        {c("Unavailable: ", "사용 불가: ")}
                        {v[key]}
                      </option>
                    )}
                  {targets
                    .filter(
                      (t) => t.kind === (key === "target_id" ? "DUT" : "SINK"),
                    )
                    .map((t) => (
                      <option key={t.id} value={t.id}>
                        {t.name} · {t.address}
                      </option>
                    ))}
                </select>
              </Field>
            ))}
          </div>
        </div>
      </section>
      <section>
        <h3>{c("Traffic and expected policy", "트래픽과 기대 정책")}</h3>
        <p className="muted">
          {c(
            "Replay supports TCP/UDP/DNS; k6 requires HTTP and no PCAP metadata. Select a consistent protocol explicitly.",
            "재생은 TCP/UDP/DNS를 지원합니다. k6는 HTTP이며 PCAP 메타데이터가 없어야 합니다. 일치하는 프로토콜을 명시적으로 선택하세요.",
          )}
        </p>
        <div className="scenario-grid">
          <Field label={label(locale, "profile_id")}>
            <select
              value={v.profile_id}
              disabled={locked}
              onChange={(e) => update("profile_id", e.target.value)}
            >
              {Object.values(scenarioProfiles).map((p) => (
                <option key={p.id} value={p.id}>
                  {text(p.name, locale)}
                </option>
              ))}
            </select>
          </Field>
          {select("protocol", ["TCP", "UDP", "DNS", "HTTP"])}
          {select("ip_version", ["4", "6"])}
          {select("expected_action", ["ALLOW", "BLOCK", "ALERT"])}
          {select("delivery_expectation", ["ALLOW", "BLOCK"])}
          <Field label={label(locale, "detection_required")}>
            <input
              type="checkbox"
              checked={draft.detection}
              disabled={locked}
              onChange={(e) =>
                change({ ...draft, detection: e.target.checked })
              }
            />
          </Field>
        </div>
        <p className="muted">
          {c(
            "Allow/Block delivery must match the action. Alert requires detection, a deadline and DUT events; delivery is an independent choice.",
            "허용/차단 시 전달 기대값은 동작과 일치해야 합니다. 경보는 탐지, 제한 시간, DUT 이벤트가 필수이며 전달 여부는 별도 선택입니다.",
          )}
        </p>
      </section>
      <section>
        <h3>{c("Declared PCAP identity", "선언된 PCAP 식별 정보")}</h3>
        <Notice tone="warning">
          {c(
            "Metadata only: no file is opened, imported or verified. A missing replay asset remains missing.",
            "메타데이터만 기록합니다. 파일을 열거나 가져오거나 검증하지 않습니다. 재생 자산 미등록은 미등록으로 유지됩니다.",
          )}
        </Notice>
        <Field label={label(locale, "pcap_declared")}>
          <input
            type="checkbox"
            checked={draft.asset}
            disabled={locked}
            onChange={(e) => change({ ...draft, asset: e.target.checked })}
          />
        </Field>
        {draft.asset && (
          <div className="scenario-grid">
            {textField("asset_label")}
            {textField("asset_sha256")}
            {numeric("asset_size_bytes", 1, 67108864)}
          </div>
        )}
      </section>
      <section>
        <h3>{c("Traffic budget", "트래픽 예산")}</h3>
        <Notice tone="warning">
          {c(
            "No safe defaults. Enter every budget. These representational ceilings are not device-safe limits or approval; actual replay session counting is not established.",
            "안전한 기본값은 없습니다. 모든 예산을 입력하세요. 표현 상한은 장비 안전 한도나 승인이 아니며 실제 재생 세션 계측을 보장하지 않습니다.",
          )}
        </Notice>
        <div className="scenario-grid">
          {(Object.keys(budgetBounds) as (keyof typeof budgetBounds)[]).map(
            (key) => numeric(key, 1, budgetBounds[key]),
          )}
        </div>
      </section>
      <section>
        <h3>{c("Success criteria", "성공 기준")}</h3>
        <p className="muted">
          {c(
            "Expected bounds, not measurements. Minimum ≤ maximum; Allow maximum is 100; Block minimum is 0. A deadline is required only when detection is required.",
            "측정 결과가 아닌 기대 범위입니다. 최소 ≤ 최대, 허용 시 최대 100, 차단 시 최소 0입니다. 탐지 필수인 경우에만 제한 시간이 필요합니다.",
          )}
        </p>
        <div className="scenario-grid">
          {numeric("minimum_delivery_pct", 0, 100)}
          {numeric("maximum_delivery_pct", 0, 100)}
          {numeric("detection_deadline_ms", 1, 60000, true)}
        </div>
      </section>
      <section>
        <h3>{c("Stop conditions", "중지 조건")}</h3>
        <div className="scenario-grid">
          {numeric("max_legitimate_loss_pct", 0, 100)}
          {numeric("max_service_latency_ms", 1, 60000)}
          {numeric("max_cpu_pct", 1, 100, true)}
          {numeric("max_memory_pct", 1, 100, true)}
          {numeric("max_sessions", 1, 1000000, true)}
          <Field
            label={label(locale, "management_loss")}
            hint={c(
              "Mandatory. Emergency and operator stop cannot be disabled.",
              "필수입니다. 비상 및 운영자 중지는 비활성화할 수 없습니다.",
            )}
          >
            <input type="checkbox" checked disabled />
          </Field>
        </div>
      </section>
      <fieldset className="scenario-evidence">
        <legend>{c("Required evidence", "필수 증거")}</legend>
        <p>
          {c(
            "Select service probe for every definition; ingress and egress PCAP for replay; DUT events for detection; resource metrics for CPU/memory/session thresholds.",
            "모든 정의에 정상 서비스 프로브, 재생에 앞단·뒷단 PCAP, 탐지에 DUT 이벤트, CPU·메모리·세션 임계값에 자원 메트릭을 선택하세요.",
          )}
        </p>
        {evidenceRoles.map((role) => (
          <Field key={role} label={label(locale, role)}>
            <input
              type="checkbox"
              checked={draft.evidence.includes(role)}
              disabled={locked}
              onChange={(e) =>
                change({
                  ...draft,
                  evidence: e.target.checked
                    ? [...draft.evidence, role]
                    : draft.evidence.filter((r) => r !== role),
                })
              }
            />
          </Field>
        ))}
      </fieldset>
    </div>
  );
}
