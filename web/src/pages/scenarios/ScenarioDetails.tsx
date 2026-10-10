import type { Locale } from "../../lib/contracts";
import { Badge, Notice } from "../../components/ui";
import { choose, text } from "../../lib/i18n";
import { label, type LabelKey } from "./labels";
import type { ScenarioVersion } from "./types";
export function ScenarioDetails({
  record,
  locale,
}: {
  record: ScenarioVersion;
  locale: Locale;
}) {
  const c = (en: string, ko: string) => choose(locale, en, ko),
    d = record.definition;
  const display = (v: unknown) =>
    v === null
      ? c("Not configured", "미설정")
      : typeof v === "boolean"
        ? v
          ? c("Yes", "예")
          : c("No", "아니요")
        : String(v);
  const group = (title: string, values: Record<string, unknown>) => (
    <section>
      <h3>{title}</h3>
      <dl className="detail-list">
        {Object.entries(values).map(([key, value]) => (
          <div key={key}>
            <dt>{label(locale, key as LabelKey)}</dt>
            <dd>{display(value)}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
  return (
    <div className="form-stack scenario-record">
      <Badge tone="warning">
        {c(
          "Definition only · not approved · not executed",
          "정의 전용 · 미승인 · 미실행",
        )}
      </Badge>
      <h3>{d.name}</h3>
      <dl className="detail-list">
        <div>
          <dt>{c("Scenario ID", "시나리오 ID")}</dt>
          <dd className="mono">{record.id}</dd>
        </div>
        <div>
          <dt>{c("Version", "버전")}</dt>
          <dd>{record.version}</dd>
        </div>
        <div>
          <dt>{c("Created", "생성 시각")}</dt>
          <dd>
            <time dateTime={record.created_at}>{record.created_at}</time>
          </dd>
        </div>
        <div>
          <dt>SHA256</dt>
          <dd className="mono">{record.digest}</dd>
        </div>
        <div>
          <dt>{label(locale, "objective")}</dt>
          <dd>{d.objective}</dd>
        </div>
        <div>
          <dt>{label(locale, "dut_version")}</dt>
          <dd>{d.dut_version}</dd>
        </div>
        <div>
          <dt>{label(locale, "policy_version")}</dt>
          <dd>{d.policy_version}</dd>
        </div>
      </dl>
      {group(c("Expected policy", "기대 정책"), {
        protocol: d.protocol,
        ip_version: d.ip_version,
        expected_action: d.expected_action,
        delivery_expectation: d.delivery_expectation,
        detection_required: d.detection_required,
      })}
      <section>
        <h3>{c("Frozen target snapshots", "고정된 대상 스냅샷")}</h3>
        {[record.target_snapshot, record.sink_snapshot].map((t) => (
          <dl className="detail-list" key={t.id}>
            <div>
              <dt>
                {t.kind === "DUT"
                  ? label(locale, "target_id")
                  : label(locale, "sink_id")}
              </dt>
              <dd>{t.name}</dd>
            </div>
            <div>
              <dt>ID</dt>
              <dd className="mono">{t.id}</dd>
            </div>
            <div>
              <dt>{c("Address (unresolved)", "주소 (미해석)")}</dt>
              <dd>{t.address}</dd>
            </div>
            <div>
              <dt>{c("Kind / status", "유형 / 상태")}</dt>
              <dd>
                {t.kind} · {c("Draft", "초안")}
              </dd>
            </div>
            <div>
              <dt>{c("Registered", "등록 시각")}</dt>
              <dd>{t.created_at}</dd>
            </div>
          </dl>
        ))}
      </section>
      <section>
        <h3>{c("Frozen profile snapshot", "고정된 프로필 스냅샷")}</h3>
        <p>{text(record.profile_snapshot.name, locale)}</p>
        <p>{text(record.profile_snapshot.description, locale)}</p>
        <p className="mono">
          {record.profile_snapshot.id} · {record.profile_snapshot.engine} ·{" "}
          {record.profile_snapshot.layer} · {record.catalog_version}
        </p>
      </section>
      {d.pcap_asset ? (
        group(
          c(
            "Declared PCAP identity — unverified",
            "선언된 PCAP 식별 정보 — 미검증",
          ),
          {
            asset_label: d.pcap_asset.label,
            asset_sha256: d.pcap_asset.sha256,
            asset_size_bytes: d.pcap_asset.size_bytes,
          },
        )
      ) : (
        <Notice tone="warning">
          {c(
            "PCAP asset missing / not declared. No file was imported or verified.",
            "PCAP 자산 미등록 / 미선언. 파일을 가져오거나 검증하지 않았습니다.",
          )}
        </Notice>
      )}
      {group(
        c(
          "Traffic budget — not safety approval",
          "트래픽 예산 — 안전 승인 아님",
        ),
        d.traffic_budget,
      )}
      {group(
        c(
          "Success criteria — expected, not measured",
          "성공 기준 — 기대값이며 측정값 아님",
        ),
        d.success_criteria,
      )}
      {group(c("Stop conditions", "중지 조건"), d.stop_conditions)}
      <section>
        <h3>{c("Required evidence", "필수 증거")}</h3>
        <ul>
          {d.evidence_requirements.map((role) => (
            <li key={role}>{label(locale, role)}</li>
          ))}
        </ul>
      </section>
      <Notice>
        {c(
          "Emergency/operator stop remains mandatory. Snapshots and digests are local declarations, not authenticated provenance, feasibility or execution approval.",
          "비상·운영자 중지는 항상 필수입니다. 스냅샷과 다이제스트는 로컬 선언이며 출처 인증, 실행 가능성 또는 실행 승인이 아닙니다.",
        )}
      </Notice>
    </div>
  );
}
