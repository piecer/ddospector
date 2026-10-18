import { useState } from "react";
import type { Locale } from "../../lib/contracts";
import { choose } from "../../lib/i18n";
import { Badge, Button, Dialog, Field, Panel } from "../../components/ui";
import { useChat } from "./useChat";
import { validText } from "./chat-wire";
import "./chat.css";
export function ChatPanel({
  locale,
  mutationsEnabled = true,
}: {
  locale: Locale;
  mutationsEnabled?: boolean;
}) {
  const c = (en: string, ko: string) => choose(locale, en, ko);
  const chat = useChat(locale, mutationsEnabled);
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
      title={c("Chat only", "대화 전용")}
      className="chat-panel"
      actions={<Badge>CHAT_ONLY</Badge>}
    >
      <p>
        {c(
          "Text chat only. No settings tools, device actions, or MCP execution.",
          "텍스트 대화 전용입니다. 설정 도구, 장치 작업, MCP 실행은 불가능합니다.",
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
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void chat.send();
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
                void chat.send();
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
