import { useCallback, useRef, useState } from "react";
import type { Locale, TargetExpectation } from "../../lib/contracts";
import { choose } from "../../lib/i18n";
import { Badge, Button, Dialog, Field, Panel } from "../../components/ui";
import { useChat } from "./useChat";
import { validText } from "./chat-wire";
import { useToolAuthority } from "./useToolAuthority";
import type {
  DecisionLedger,
  TranscriptLedger,
  ToolReadGate,
} from "./useToolTranscript";
import type { RequestedAuthority, ToolTranscript } from "./chat-tool-types";
import { ToolRecords } from "./ToolRecords";
import "./chat.css";
export function ChatPanel({
  locale,
  mutationsEnabled = true,
  onSaved,
  onViewSaved,
  onViewTarget,
}: {
  locale: Locale;
  mutationsEnabled?: boolean;
  onSaved?: () => Promise<void>;
  onViewSaved?: () => void;
  onViewTarget?: (expectation: TargetExpectation) => void;
}) {
  const c = (en: string, ko: string) => choose(locale, en, ko);
  const authority = useToolAuthority(mutationsEnabled);
  const [toolConsent, setToolConsent] = useState(false);
  const [scope, setScope] = useState<RequestedAuthority>("agent_v1");
  const canGrant =
    authority.canGrant && (scope === "agent_v1" || authority.targetSupported);
  const chat = useChat(locale, mutationsEnabled, canGrant, scope);
  const send = () => {
    if (toolConsent && !canGrant) return;
    if (
      chat.busy ||
      chat.uncertain ||
      !chat.session ||
      chat.session.active_turn_id ||
      !validText(chat.input, 8192, true)
    )
      return;
    void chat.send(toolConsent);
    setToolConsent(false);
  };
  const decisions = useRef<DecisionLedger>(new Map());
  const records = useRef<TranscriptLedger>(new Map());
  const readGate = useRef<ToolReadGate>({ owner: null, completed: -Infinity });
  const savedSeen = useRef(new Set<string>());
  const [savedStale, setSavedStale] = useState(false);
  const refreshSaved = useCallback(async () => {
    try {
      await onSaved?.();
      setSavedStale(false);
    } catch {
      setSavedStale(true);
    }
  }, [onSaved]);
  const observeRecords = useCallback(
    (record: ToolTranscript) => {
      authority.observe(record);
      for (const call of record.calls)
        if (
          call.status === "succeeded" &&
          (call.result?.kind === "agent_profile_updated" ||
            call.result?.kind === "target_created") &&
          !savedSeen.current.has(call.id)
        ) {
          savedSeen.current.add(call.id);
          void refreshSaved();
        }
    },
    [authority.observe, refreshSaved],
  );
  const [consent, setConsent] = useState(false);
  const profile = chat.runtime?.profile;
  const status =
    chat.phase === "ready" && chat.currentTurn
      ? chat.currentTurn.status
      : chat.phase;
  const statuses: Record<string, [string, string]> = {
    rejected: [
      "Request not accepted. Your input is preserved.",
      "요청이 접수되지 않았습니다. 입력은 유지됩니다.",
    ],
    history: ["Older history", "이전 기록"],
    "stop-unknown": [
      "Stop outcome unconfirmed. Read back; remote generation may continue.",
      "중지 결과가 확인되지 않았습니다. 다시 읽으세요. 원격 생성은 계속될 수 있습니다.",
    ],
    loading: ["Loading chat…", "대화 불러오는 중…"],
    ready: ["Ready", "준비됨"],
    starting: ["Creating conversation…", "대화 만드는 중…"],
    sending: ["Awaiting acceptance…", "접수 확인 중…"],
    observing: ["Receiving response…", "응답 수신 중…"],
    succeeded: ["Succeeded", "완료"],
    failed: ["Failed — partial text retained", "실패 — 부분 응답 보존됨"],
    cancelled: ["Cancelled locally", "로컬 취소됨"],
    interrupted: ["Interrupted — not replayed", "중단됨 — 재전송하지 않음"],
    accepted: ["Accepted", "접수됨"],
    running: ["Running", "실행 중"],
    cancel_requested: [
      "Stop requested; waiting for cleanup",
      "중지 요청됨; 정리 대기 중",
    ],
    detached: [
      "Observation ended. Read back to check progress.",
      "관찰이 종료되었습니다. 상태를 다시 읽으세요.",
    ],
    "read-error": [
      "Unable to read chat. Existing text is preserved.",
      "대화를 읽을 수 없습니다. 기존 텍스트는 유지됩니다.",
    ],
    "grant-recovered": [
      "Read/propose grant recovered; explicitly continue the captured message or revoke it.",
      "읽기/제안 권한을 복구했습니다. 원래 메시지 전송을 명시적으로 계속하거나 권한을 취소하세요.",
    ],
    "unknown-send": [
      "Send outcome unknown. Do not resend; read back first.",
      "전송 결과를 알 수 없습니다. 재전송하지 말고 먼저 다시 읽으세요.",
    ],
    "unknown-session": [
      "Conversation creation is unconfirmed. Refresh history before starting another.",
      "대화 생성이 확인되지 않았습니다. 새 대화를 시작하기 전에 기록을 새로고침하세요.",
    ],
  };
  const message = statuses[status] ?? statuses.ready;
  return (
    <Panel
      title={c("Chat", "대화")}
      className="chat-panel"
      actions={<Badge>{toolConsent ? "READ / PROPOSE" : "CHAT_ONLY"}</Badge>}
    >
      <p>
        {c(
          "Text-only by default. Optional next-message Agent/Skill reads and one proposal require explicit consent; writing requires separate exact approval. No device actions or MCP execution.",
          "기본은 텍스트 전용입니다. 다음 메시지의 에이전트/스킬 읽기와 제안에는 명시적 동의가, 저장에는 별도 승인이 필요합니다. 장치 작업이나 MCP 실행은 불가능합니다.",
        )}
      </p>
      {profile && (
        <div className="chat-binding">
          <span>{profile.model}</span>
          <code>{profile.endpoint}</code>
          <small>
            {c(
              "Supported configuration metadata — connection not tested.",
              "지원되는 설정 메타데이터이며 연결을 테스트한 상태가 아닙니다.",
            )}
          </small>
        </div>
      )}
      {chat.runtime && !chat.runtime.supported && (
        <p>
          {c(
            "Chat configuration is unsupported or missing.",
            "대화 설정이 없거나 지원되지 않습니다.",
          )}{" "}
          {chat.runtime.reason}
        </p>
      )}
      <p className="muted">
        {c(
          "Persistent history · input 8 KiB · output 64 KiB · 120 seconds per turn. Leaving this page only detaches observation; generation continues within that budget.",
          "영구 기록 · 입력 8 KiB · 출력 64 KiB · 턴당 120초. 페이지를 떠나면 관찰만 종료되며 생성은 제한 시간 내 계속됩니다.",
        )}
      </p>
      <div className="button-row">
        <Button
          data-testid="chat-new-session"
          disabled={
            !mutationsEnabled ||
            !chat.runtime?.supported ||
            chat.busy ||
            chat.uncertain ||
            chat.uncertainSession
          }
          onClick={() => setConsent(true)}
        >
          {c("New conversation", "새 대화")}
        </Button>
        <Button onClick={() => void chat.refresh()} disabled={chat.busy}>
          {c("Refresh chat metadata", "대화 메타데이터 새로고침")}
        </Button>
      </div>
      <nav
        data-testid="chat-history"
        className="chat-history"
        aria-label={c("Saved conversations", "저장된 대화")}
      >
        <h3>{c("Persistent history", "영구 기록")}</h3>
        {chat.sessions.length === 0 && (
          <p>{c("No loaded conversations.", "불러온 대화가 없습니다.")}</p>
        )}
        {chat.sessions.map((s) => (
          <Button
            key={s.id}
            data-testid={`chat-session-${s.id}`}
            disabled={chat.busy}
            aria-current={chat.session?.id === s.id ? "true" : undefined}
            onClick={() => void chat.open(s.id)}
          >
            {s.model} · {s.created_at} · {s.id}
          </Button>
        ))}
      </nav>
      {chat.session && (
        <div className="chat-binding">
          <small>
            {c("Approved conversation destination", "승인된 대화 대상")}
          </small>
          <span>{chat.session.model}</span>
          <code>{chat.session.endpoint}</code>
        </div>
      )}
      <div className="button-row">
        <Button
          data-testid="chat-older"
          disabled={
            !chat.session ||
            chat.nextBefore === null ||
            chat.busy ||
            chat.reading
          }
          onClick={() => {
            if (chat.session && chat.nextBefore !== null)
              void chat.open(chat.session.id, chat.nextBefore);
          }}
        >
          {c("Older messages", "이전 메시지")}
        </Button>
        <Button
          data-testid="chat-newest"
          disabled={!chat.session || chat.busy || chat.reading}
          onClick={() => {
            if (chat.session) void chat.open(chat.session.id);
          }}
        >
          {c("Newest / read back", "최신 / 다시 읽기")}
        </Button>
        <Button
          data-testid="chat-stop"
          variant="danger"
          disabled={
            !chat.session?.active_turn_id || chat.stopping || chat.stopRequested
          }
          onClick={() => void chat.stop()}
        >
          {c("Stop", "중지")}
        </Button>
      </div>
      <p className="muted">
        {c(
          "Stop closes local work and transport; remote generation may continue. Failed or partial exchanges stay in history but are excluded from future model context. Context is capped at 128 KiB; start a new conversation if full. No automatic compression or replay.",
          "중지는 로컬 작업과 연결을 종료하지만 원격 생성은 계속될 수 있습니다. 실패하거나 부분 완료된 대화는 기록에 남지만 이후 모델 컨텍스트에서는 제외됩니다. 컨텍스트는 128 KiB로 제한됩니다. 가득 차면 새 대화를 시작하세요. 자동 압축이나 재전송은 없습니다.",
        )}
      </p>
      {chat.recoveredGrant && (
        <div>
          <p>
            {c(
              "Recovered exact message / session (not current editor text)",
              "복구한 원본 메시지 / 세션 (현재 편집기 텍스트 아님)",
            )}
          </p>
          <pre className="chat-text">{chat.recoveredGrant.text}</pre>
          <p className="chat-text">{chat.recoveredGrant.session}</p>
          <Button
            data-testid="chat-tools-grant-continue"
            disabled={
              chat.busy ||
              !authority.canGrant ||
              chat.recoveredGrant.grant.status !== "pending"
            }
            onClick={() => void chat.continueGrant()}
          >
            {c(
              "Continue this exact granted message",
              "이 권한의 원본 메시지 전송 계속",
            )}
          </Button>
          <Button
            data-testid="chat-tools-grant-revoke"
            disabled={chat.busy}
            onClick={() => void chat.revokeGrant()}
          >
            {c("Revoke unused grant", "미사용 권한 취소")}
          </Button>
        </div>
      )}
      {chat.uncertain && (
        <Button
          disabled={chat.busy}
          onClick={() => void chat.recoverSubmission()}
        >
          {c("Read uncertain submission", "미확인 전송 다시 읽기")}
        </Button>
      )}
      <p
        data-testid="chat-status"
        role="status"
        aria-live="polite"
        aria-atomic="true"
      >
        {c(...message)}
        {chat.errorCode ? ` · ${chat.errorCode}` : ""}
      </p>
      <div
        data-testid="chat-transcript"
        role="region"
        aria-label={c("Conversation transcript", "대화 내용")}
        className="chat-transcript"
        tabIndex={0}
      >
        {chat.turns.map((turn) => (
          <article key={turn.id}>
            <h3>
              {c(
                `You · turn ${turn.sequence}`,
                `사용자 · ${turn.sequence}번째 턴`,
              )}
            </h3>
            <p className="chat-text">{turn.user_text}</p>
            <h3>{c("Assistant", "어시스턴트")}</h3>
            <p className="chat-text">{turn.assistant_text}</p>
            <small>
              {c(...(statuses[turn.status] ?? statuses.ready))}
              {turn.error_code ? ` · ${turn.error_code}` : ""}
            </small>
            <ToolRecords
              turn={turn}
              locale={locale}
              enabled={chat.toolTurns.includes(turn.id)}
              viewEpoch={chat.viewEpoch}
              canWrite={authority.canWrite}
              onRecord={observeRecords}
              onViewSaved={onViewSaved}
              onViewTarget={onViewTarget}
              decisions={decisions.current}
              records={records.current}
              readGate={readGate.current}
            />
          </article>
        ))}
        {!chat.session && (
          <p>
            {c(
              "Start a conversation or open saved history.",
              "새 대화를 시작하거나 저장된 기록을 여세요.",
            )}
          </p>
        )}
      </div>
      {chat.before !== undefined && (
        <p>
          {c(
            "Reading older messages. Return to newest to send.",
            "이전 메시지를 읽는 중입니다. 전송하려면 최신 기록으로 돌아가세요.",
          )}
        </p>
      )}
      {chat.session?.sequence === 64 && (
        <p>
          {c(
            "This conversation reached 64 turns. Start a new conversation to continue.",
            "이 대화는 64턴에 도달했습니다. 계속하려면 새 대화를 시작하세요.",
          )}
        </p>
      )}
      {savedStale && (
        <div role="status">
          <p>
            {c(
              "Saved, but workspace view is stale. Your unsaved assignment is preserved.",
              "저장되었지만 워크스페이스 화면이 최신이 아닙니다. 저장하지 않은 할당 초안은 유지됩니다.",
            )}
          </p>
          <Button
            data-testid="chat-tools-workspace-refresh"
            onClick={() => void refreshSaved()}
          >
            {c(
              "Retry workspace read (no write)",
              "워크스페이스 읽기 재시도 (쓰기 없음)",
            )}
          </Button>
        </div>
      )}
      {chat.runtime?.supported && (
        <Field label={c("Tool permission scope", "도구 허용 범위")}>
          <select
            data-testid="chat-tool-scope"
            value={scope}
            disabled={
              !mutationsEnabled ||
              chat.busy ||
              chat.uncertain ||
              !!chat.session?.active_turn_id ||
              [...decisions.current.entries()].some(
                ([turnId, d]) =>
                  !records.current
                    .get(turnId)
                    ?.calls.some(
                      (call) =>
                        call.id === d.call &&
                        call.decision?.request_id === d.input.request_id &&
                        call.decision?.proposal_digest ===
                          d.input.proposal_digest &&
                        call.decision?.decision === d.input.decision,
                    ),
              )
            }
            onChange={(e) => {
              if (
                e.target.value === "agent_v1" ||
                (e.target.value === "target_create_v2" &&
                  authority.targetSupported)
              ) {
                setScope(e.target.value);
                setToolConsent(false);
              }
            }}
          >
            <option value="agent_v1">
              {c("Agent settings", "에이전트 설정")}
            </option>
            <option
              value="target_create_v2"
              disabled={!authority.targetSupported}
            >
              {c("Create target", "대상 생성")}
            </option>
          </select>
        </Field>
      )}
      {chat.runtime?.supported && (
        <label className="chat-tool-consent">
          <input
            type="checkbox"
            data-testid="chat-tools-toggle"
            checked={toolConsent}
            disabled={
              !mutationsEnabled ||
              chat.busy ||
              chat.uncertain ||
              !!chat.session?.active_turn_id
            }
            onChange={(e) => {
              setToolConsent(e.target.checked);
              if (e.target.checked) void authority.refresh();
            }}
          />
          <span>
            {scope === "target_create_v2"
              ? c(
                  "For the exact next message only: allow target reads and one target creation proposal. No write authority; separate exact approval is required.",
                  "정확히 다음 메시지만: 대상 읽기와 대상 생성 제안 1건에 동의합니다. 저장 권한이 아니며 정확한 제안에 별도 승인이 필요합니다.",
                )
              : c(
                  "For the exact next message only: allow reading Agent/Skill configuration and proposing one Agent name / complete Skill-list change. This grants no write authority. A separate exact approval is always required.",
                  "정확히 다음 메시지만: 에이전트/스킬 설정 읽기 및 에이전트 이름/전체 스킬 목록 변경 1건 제안에 동의합니다. 저장 권한은 부여하지 않으며 정확한 변경에 대한 별도 승인이 항상 필요합니다.",
                )}
          </span>
        </label>
      )}
      <p data-testid="chat-tools-status" role="status">
        {authority.fence?.fenced
          ? c(
              "Tool writes fenced — prior execution remains uncertain. Consented reads remain available.",
              "도구 쓰기 차단 — 이전 실행 미확인. 동의한 읽기는 가능합니다.",
            ) + ` (${authority.fence.generation})`
          : toolConsent && !authority.canGrant
            ? c(
                "Tool authority unavailable. Read configuration status before sending.",
                "도구 권한을 사용할 수 없습니다. 전송 전에 설정 상태를 읽으세요.",
              )
            : c(
                "No write authority from consent or model prose.",
                "동의나 모델 문구에는 저장 권한이 없습니다.",
              )}
      </p>
      {authority.fence && (
        <p data-testid="chat-tools-fence-generation">
          {c("Fence generation", "차단 세대")} {authority.fence.generation}
        </p>
      )}
      <Button
        data-testid="chat-tools-reconcile-review"
        onClick={() => void authority.inspect()}
        disabled={authority.reconciling}
      >
        {c(
          "Review uncertain execution and current configuration",
          "미확인 실행 및 현재 설정 검토",
        )}
      </Button>
      {authority.review && (
        <div className="chat-reconcile-review">
          <h4>
            {c(
              "Immutable uncertain operation (not proof of saving)",
              "변경 불가능한 미확인 작업 (저장 증거 아님)",
            )}
          </h4>
          {authority.review.calls.map((call) => (
            <pre className="chat-text" key={call.id}>
              {JSON.stringify(call, null, 2)}
            </pre>
          ))}
          <div
            data-testid={
              authority.review.targets
                ? "chat-tools-current-targets"
                : "chat-tools-current-agent"
            }
          >
            <h4>
              {c(
                authority.review.targets
                  ? "Independently refreshed current target inventory — matching names do not prove ownership"
                  : "Independently refreshed current Agent",
                authority.review.targets
                  ? "별도로 새로 읽은 현재 대상 목록 — 같은 이름은 소유 증거 아님"
                  : "별도로 새로 읽은 현재 에이전트",
              )}
            </h4>
            <p>
              {c("Current draft revision", "현재 초안 리비전")}{" "}
              {authority.review.fence.current_draft_revision}
            </p>
            <pre className="chat-text">
              {JSON.stringify(
                authority.review.targets ?? authority.review.agent,
                null,
                2,
              )}
            </pre>
          </div>
          <p>
            {c(
              "I acknowledge the prior execution is not proven. This only clears this write fence; prior outcomes remain uncertain and no configuration is rewritten.",
              "이전 실행이 입증되지 않았음을 확인합니다. 이 쓰기 차단만 해제하며 이전 결과는 미확인으로 유지되고 설정은 다시 저장되지 않습니다.",
            )}
          </p>
          <Button
            data-testid="chat-tools-reconcile-confirm"
            disabled={!authority.canReconcile || !!chat.session?.active_turn_id}
            onClick={() => void authority.acknowledge()}
          >
            {c(
              "Acknowledge uncertainty for this generation/revision",
              "이 세대/리비전의 불확실성 확인",
            )}
          </Button>
        </div>
      )}
      {authority.reviewState === "history-required" && (
        <p>
          {c(
            "Open the uncertain turn in history before acknowledging; current state alone is not proof.",
            "확인하기 전에 기록에서 미확인 턴을 여세요. 현재 상태만으로는 증명할 수 없습니다.",
          )}
        </p>
      )}
      {authority.reviewState === "unknown" && (
        <p>
          {c(
            "Reconciliation/read outcome unknown. Read only; do not resubmit.",
            "조정/읽기 결과 미확인. 다시 전송하지 말고 읽기만 하세요.",
          )}
        </p>
      )}
      {authority.receipt && (
        <p>
          {c(
            "Historical acknowledgement only; prior outcomes remain uncertain. Cleared generation:",
            "이전 확인 기록일 뿐이며 결과는 미확인으로 유지됩니다. 해제 세대:",
          )}{" "}
          {authority.receipt.generation}
        </p>
      )}
      <Button onClick={() => void authority.refresh()}>
        {c("Read tool availability / fence", "도구 사용 가능 여부 / 차단 읽기")}
      </Button>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          send();
        }}
        aria-label={c("Send a message", "메시지 보내기")}
      >
        <Field
          label={c("Message", "메시지")}
          hint={
            chat.input && !validText(chat.input, 8192, true)
              ? c(
                  "Use nonblank valid text up to 8192 UTF-8 bytes, without NUL.",
                  "NUL 없는 유효한 텍스트를 8192 UTF-8 바이트 이내로 입력하세요. 공백만 입력할 수 없습니다.",
                )
              : c(
                  "Enter to send · Shift+Enter for a newline",
                  "Enter로 전송 · Shift+Enter로 줄바꿈",
                )
          }
        >
          <textarea
            maxLength={8192}
            aria-invalid={!!chat.input && !validText(chat.input, 8192, true)}
            data-testid="chat-input"
            value={chat.input}
            disabled={!chat.session}
            onChange={(e) => chat.setInput(e.target.value)}
            rows={4}
            onKeyDown={(e) => {
              if (
                e.key === "Enter" &&
                !e.shiftKey &&
                !e.nativeEvent.isComposing &&
                e.keyCode !== 229
              ) {
                e.preventDefault();
                send();
              }
            }}
          />
        </Field>
        <Button
          type="submit"
          variant="primary"
          data-testid="chat-send"
          disabled={
            !mutationsEnabled ||
            (toolConsent && !canGrant) ||
            !chat.session ||
            !!chat.session.active_turn_id ||
            chat.session.sequence >= 64 ||
            chat.busy ||
            chat.uncertain ||
            chat.reading ||
            chat.before !== undefined ||
            !validText(chat.input, 8192, true)
          }
        >
          {c("Send", "전송")}
        </Button>
      </form>
      <Dialog
        open={consent}
        title={c("Approve this chat destination", "대화 전송 대상 승인")}
        onClose={() => setConsent(false)}
      >
        <p>
          {c(
            "Your messages and successful conversation context will be sent to this model and endpoint. This does not authorize tools or device actions.",
            "메시지와 성공한 대화의 컨텍스트가 아래 모델 및 엔드포인트로 전송됩니다. 도구나 장치 작업은 승인하지 않습니다.",
          )}
        </p>
        <p>
          {c(...message)}
          {chat.errorCode ? ` · ${chat.errorCode}` : ""}
        </p>
        {chat.uncertainSession && (
          <Button onClick={() => void chat.refresh()}>
            {c(
              "Read conversation creation outcome",
              "대화 생성 결과 다시 읽기",
            )}
          </Button>
        )}
        <p className="chat-text">{profile?.model}</p>
        <p className="chat-text">{profile?.endpoint}</p>
        <Button
          data-testid="chat-start-confirm"
          disabled={!mutationsEnabled || chat.busy || chat.uncertainSession}
          onClick={() =>
            void chat.start().then((ok) => {
              if (ok) setConsent(false);
            })
          }
        >
          {c("Approve and start conversation", "승인하고 대화 시작")}
        </Button>
      </Dialog>
    </Panel>
  );
}
