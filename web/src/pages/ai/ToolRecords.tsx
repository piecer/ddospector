import { useEffect } from "react";
import type { ScenarioCallContext } from "./chat-tool-client";
import type {
  ScenarioStateInspection,
  ScenarioExpectation,
} from "./chat-scenario-types";
import type { ToolTranscript } from "./chat-tool-types";
import type {
  Locale,
  TargetExpectation,
  SkillExpectation,
} from "../../lib/contracts";
import { choose } from "../../lib/i18n";
import { Button } from "../../components/ui";
import type { ChatTurn } from "./chat-types";
import { terminal } from "./chat-wire";
import type {
  DecisionLedger,
  TranscriptLedger,
  ToolReadGate,
} from "./useToolTranscript";
import { useToolTranscript } from "./useToolTranscript";
export function ToolRecords({
  turn,
  locale,
  enabled,
  viewEpoch,
  canWrite,
  onRecord,
  onViewSaved,
  onViewTarget,
  onViewSkill,
  onScenarioSaved,
  decisions,
  records,
  readGate,
  scenarioContext,
  scenarioState,
  draftRevision,
  onDecisionPending,
}: {
  turn: ChatTurn;
  locale: Locale;
  enabled: boolean;
  viewEpoch: number;
  canWrite: boolean;
  onRecord?: (record: ToolTranscript) => void;
  onViewSaved?: () => void;
  onViewTarget?: (expectation: TargetExpectation) => void;
  onViewSkill?: (expectation: SkillExpectation) => void;
  onScenarioSaved?: (expectation: ScenarioExpectation) => void;
  decisions?: DecisionLedger;
  records?: TranscriptLedger;
  readGate?: ToolReadGate;
  scenarioContext?: ScenarioCallContext;
  scenarioState?: ScenarioStateInspection | null;
  draftRevision?: number | null;
  onDecisionPending?: (turn: string, pending: boolean) => void;
}) {
  const tools = useToolTranscript(
    turn,
    enabled,
    viewEpoch,
    decisions,
    records,
    readGate,
    scenarioContext,
  );
  useEffect(() => {
    if (tools.record && !tools.stale) onRecord?.(tools.record);
  }, [tools.record, tools.stale, onRecord]);
  useEffect(() => {
    onDecisionPending?.(
      turn.id,
      tools.decisionState === "sending" || tools.decisionState === "unknown",
    );
  }, [turn.id, tools.decisionState, onDecisionPending]);
  const scenarioAllowed = (
    proposal: import("./chat-tool-types").ToolProposal,
  ) =>
    !("schema_version" in proposal) ||
    proposal.schema_version !== 4 ||
    (scenarioState?.registry_write_status === "available" &&
      scenarioState.scenario_revision === proposal.expected_scenario_revision &&
      draftRevision === proposal.expected_draft_revision);
  const c = (en: string, ko: string) => choose(locale, en, ko);
  if (!enabled) return null;
  return (
    <section
      className="chat-tool-records"
      data-testid={`chat-tools-${turn.id}`}
      aria-label={c("Authoritative tool records", "확인된 도구 기록")}
    >
      <h4>
        {c(
          "Tool facts — separate from assistant prose",
          "도구 사실 — 모델 답변과 별도",
        )}
      </h4>
      <Button
        data-testid={`chat-tools-refresh-${turn.id}`}
        onClick={tools.refresh}
      >
        {c("Read tool records (GET only)", "도구 기록 다시 읽기 (GET 전용)")}
      </Button>
      {tools.stale && (
        <p role="status">
          {c(
            "Tool outcome unknown / stale. Read again; do not resubmit.",
            "도구 결과 미확인 / 오래된 기록입니다. 재전송하지 말고 다시 읽으세요.",
          )}
        </p>
      )}
      {tools.record?.calls.length === 0 && (
        <p>{c("No recorded tool calls.", "기록된 도구 호출이 없습니다.")}</p>
      )}
      {tools.record?.calls.map((call) => (
        <div
          key={call.id}
          className="chat-tool-card"
          data-testid={`chat-tool-${call.id}`}
          data-tool-status={call.status}
        >
          <h4>
            {call.tool} · {call.status}
          </h4>
          <p className="chat-text">
            {call.id} · {call.provider_call_id}
          </p>
          <p>
            {c("Operator-authorized model · grant", "운영자 승인 모델 · 권한")}{" "}
            {call.grant_id}
          </p>
          <pre className="chat-text">
            {JSON.stringify(call.arguments, null, 2)}
          </pre>
          {call.proposal && (
            <div data-testid={`chat-tool-proposal-${call.id}`}>
              <p>
                {c(
                  "Exact proposal — no write until a separate approval",
                  "정확한 제안 — 별도 승인 전에는 저장하지 않음",
                )}
              </p>
              <p>
                {c("Draft revision", "초안 리비전")}{" "}
                {call.proposal.expected_draft_revision} · {c("Expires", "만료")}{" "}
                {call.proposal.expires_at}
              </p>
              <div className="chat-tool-diff">
                <div>
                  <h5>
                    {call.tool === "target_create" ||
                    call.tool === "skill_create"
                      ? c(
                          "New record (not a uniqueness claim)",
                          "새 레코드 (중복 없음의 증거 아님)",
                        )
                      : c("Before", "변경 전")}
                  </h5>
                  <pre className="chat-text">
                    {JSON.stringify(call.proposal.before, null, 2)}
                  </pre>
                </div>
                <div>
                  <h5>
                    {"schema_version" in call.proposal &&
                    call.proposal.schema_version === 4
                      ? c(
                          "Complete scenario definition — proposed, not executed",
                          "전체 시나리오 정의 — 제안, 미실행",
                        )
                      : call.tool === "skill_create"
                        ? c(
                            "Create Skill — literal fields",
                            "스킬 생성 — 원본 필드",
                          )
                        : call.tool === "target_create"
                          ? c(
                              "Create target — literal fields",
                              "대상 생성 — 원본 필드",
                            )
                          : c(
                              "After (complete Skill list)",
                              "변경 후 (전체 스킬 목록)",
                            )}
                  </h5>
                  {"operation" in call.proposal &&
                  call.proposal.operation === "skill_create" ? (
                    <dl>
                      {(
                        [
                          "name",
                          "description",
                          "instructions",
                          "category",
                        ] as const
                      ).map((key) => (
                        <div key={key}>
                          <dt>{key}</dt>
                          <dd>
                            <pre className="chat-text">
                              {call.proposal &&
                              "operation" in call.proposal &&
                              call.proposal.operation === "skill_create"
                                ? call.proposal.after[key]
                                : ""}
                            </pre>
                          </dd>
                        </div>
                      ))}
                    </dl>
                  ) : (
                    <pre className="chat-text">
                      {JSON.stringify(call.proposal.after, null, 2)}
                    </pre>
                  )}
                </div>
              </div>
              {"schema_version" in call.proposal &&
                call.proposal.schema_version === 4 && (
                  <>
                    <h5>
                      {c(
                        "Input source and protected inputs digest",
                        "입력 출처 및 보호 입력 다이제스트",
                      )}
                    </h5>
                    <pre className="chat-text">
                      {JSON.stringify(call.proposal.input_source, null, 2)}
                    </pre>
                    <p className="chat-text">{call.proposal.inputs_digest}</p>
                    <h5>
                      {c(
                        "Declared snapshots (not verified hardware)",
                        "선언된 스냅샷 (검증된 장비 아님)",
                      )}
                    </h5>
                    <pre className="chat-text">
                      {JSON.stringify(call.proposal.snapshots, null, 2)}
                    </pre>
                    <p>
                      {c(
                        "Scenario registry revision",
                        "시나리오 레지스트리 리비전",
                      )}{" "}
                      · {call.proposal.expected_scenario_revision}
                    </p>
                    <p>
                      {c(
                        "Execution disabled. Null means not configured. Observation criteria are proposed, not measured.",
                        "실행 비활성화. null은 미설정입니다. 관찰 기준은 제안이며 측정 결과가 아닙니다.",
                      )}
                    </p>
                  </>
                )}
              <p className="chat-text">{call.proposal.digest}</p>
              {call.status === "awaiting_approval" && (
                <div className="button-row">
                  <Button
                    data-testid={`chat-tool-approve-${call.id}`}
                    disabled={
                      !canWrite ||
                      !scenarioAllowed(call.proposal) ||
                      tools.stale ||
                      tools.decisionBlocked ||
                      terminal(turn) ||
                      Date.now() >= Date.parse(call.proposal.expires_at)
                    }
                    onClick={() =>
                      void tools.decide(
                        call,
                        "approve",
                        canWrite &&
                          !!call.proposal &&
                          scenarioAllowed(call.proposal),
                      )
                    }
                  >
                    {c("Approve this exact change", "이 변경만 승인")}
                  </Button>
                  <Button
                    data-testid={`chat-tool-deny-${call.id}`}
                    disabled={
                      tools.stale ||
                      tools.decisionBlocked ||
                      terminal(turn) ||
                      Date.now() >= Date.parse(call.proposal.expires_at)
                    }
                    onClick={() => void tools.decide(call, "deny", true)}
                  >
                    {c("Deny", "거부")}
                  </Button>
                </div>
              )}
            </div>
          )}
          {tools.decisionState !== "idle" && call.proposal && (
            <p role="status">
              {tools.decisionState === "acknowledged"
                ? c(
                    "Acknowledged — authority only, not proof of saving.",
                    "접수 확인 — 승인 권한만 확인되었으며 저장 증거가 아닙니다.",
                  )
                : tools.decisionState === "unknown"
                  ? c(
                      "Decision outcome unknown. GET-only recovery; never approve again.",
                      "결정 결과 미확인. GET으로만 복구하며 다시 승인하지 마세요.",
                    )
                  : c(
                      "Awaiting decision acknowledgement…",
                      "결정 접수 확인 중…",
                    )}
            </p>
          )}
          {call.status === "succeeded" &&
            call.result?.kind === "agent_profile_updated" && (
              <p>
                {c("Saved ·", "저장됨 ·")} {call.result.before_revision} →{" "}
                {call.result.after_revision} · {call.result.audit.id}
              </p>
            )}
          {call.status === "succeeded" &&
            call.result?.kind === "agent_profile_updated" &&
            onViewSaved && (
              <Button
                data-testid={`chat-tool-view-saved-${call.id}`}
                onClick={onViewSaved}
              >
                {c(
                  "View saved Agent in assignment form",
                  "할당 양식에서 저장된 에이전트 보기",
                )}
              </Button>
            )}
          {call.status === "succeeded" &&
            call.result?.kind === "target_created" && (
              <div>
                <p>
                  {c("Saved ·", "저장됨 ·")} {call.result.before_revision} →{" "}
                  {call.result.after_revision} · {call.result.audit.id}
                </p>
                {onViewTarget && (
                  <Button
                    data-testid={`chat-tool-view-saved-${call.id}`}
                    onClick={() => {
                      if (call.result?.kind === "target_created")
                        onViewTarget({
                          target: call.result.target,
                          after_revision: call.result.after_revision,
                        });
                    }}
                  >
                    {c(
                      "View saved target in inventory",
                      "목록에서 저장된 대상 보기",
                    )}
                  </Button>
                )}
              </div>
            )}
          {call.status === "succeeded" &&
            call.result?.kind === "skill_created" && (
              <div>
                <p>
                  {c("Saved ·", "저장됨 ·")} {call.result.before_revision} →{" "}
                  {call.result.after_revision} · {call.result.audit.id}
                </p>
                {onViewSkill && (
                  <Button
                    data-testid={`chat-tool-view-saved-${call.id}`}
                    onClick={() => {
                      if (call.result?.kind === "skill_created")
                        onViewSkill({
                          skill: call.result.skill,
                          after_revision: call.result.after_revision,
                        });
                    }}
                  >
                    {c(
                      "View saved Skill in library",
                      "라이브러리에서 저장된 스킬 보기",
                    )}
                  </Button>
                )}
              </div>
            )}
          {call.status === "succeeded" &&
            (call.result?.kind === "scenario_created" ||
              call.result?.kind === "scenario_appended") && (
              <div>
                <p>
                  {c("Saved definition ·", "정의 저장됨 ·")}{" "}
                  {call.result.before_scenario_revision} →{" "}
                  {call.result.after_scenario_revision} ·{" "}
                  {c("Source draft revision", "출처 초안 리비전")}{" "}
                  {call.result.source_draft_revision}
                </p>
                <p>
                  {c(
                    "Server-retained authority and client-checked transcript consistency; fresh history confirmation is separate.",
                    "서버 보존 권한 및 클라이언트 기록 일관성 검사. 새 이력 확인은 별도입니다.",
                  )}
                </p>
                {onScenarioSaved && (
                  <Button
                    data-testid={`chat-tool-view-saved-${call.id}`}
                    onClick={() => {
                      if (
                        call.result?.kind === "scenario_created" ||
                        call.result?.kind === "scenario_appended"
                      )
                        onScenarioSaved(
                          structuredClone({
                            scenario: call.result.scenario,
                            after_scenario_revision:
                              call.result.after_scenario_revision,
                          }),
                        );
                    }}
                  >
                    {c(
                      "View saved scenario version",
                      "저장된 시나리오 버전 보기",
                    )}
                  </Button>
                )}
              </div>
            )}
          {call.result && (
            <pre className="chat-text">
              {JSON.stringify(call.result, null, 2)}
            </pre>
          )}
          {call.error_code && <p>{call.error_code}</p>}
          {call.status === "uncertain" && (
            <p>
              {c(
                "Execution remains uncertain. Matching current values do not prove this operation saved.",
                "실행 여부는 계속 미확인입니다. 현재 값이 같아도 이 작업의 저장을 입증하지 않습니다.",
              )}
            </p>
          )}
          {call.status === "executing" && (
            <p>
              {c(
                "Settlement pending. Stop cannot undo an admitted publication.",
                "처리 완료 대기 중입니다. 중지로 이미 허용된 저장을 취소할 수 없습니다.",
              )}
            </p>
          )}
        </div>
      ))}
    </section>
  );
}
