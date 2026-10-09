import { useState } from "react";
import type { Locale } from "../../lib/contracts";
import { Button, Field, Notice } from "../../components/ui";
import { choose } from "../../lib/i18n";
import { profileIssue } from "./validation";
import type { AIModelProfile, AIProtocol } from "./types";
export function newProfile(): AIModelProfile {
  return {
    id: "llm-" + crypto.randomUUID(),
    name: "",
    format: "openai",
    model: "",
    base_url: "",
    credential_env: "",
    rate_per_second: 0,
    rate_per_minute: 0,
    context_window_k: 0,
    streaming: true,
    max_tokens: 0,
    max_tokens_field: "",
    thinking_type: "",
    reasoning_effort: "",
    retry: {
      connect: { attempts: 0, interval_ms: 0 },
      empty: { attempts: 0, interval_ms: 0 },
      stream: { attempts: 0, interval_ms: 0 },
    },
  };
}
export function ProfileEditor({
  initial,
  profiles,
  locale,
  disabled,
  onSave,
  onClose,
}: {
  initial: AIModelProfile;
  profiles: AIModelProfile[];
  locale: Locale;
  disabled: boolean;
  onSave: (value: AIModelProfile) => void;
  onClose: () => void;
}) {
  const t = (en: string, ko: string) => choose(locale, en, ko);
  const [draft, setDraft] = useState(initial);
  const [numbers, setNumbers] = useState<Record<string, string>>(() => ({
    rate_per_second: String(initial.rate_per_second),
    rate_per_minute: String(initial.rate_per_minute),
    context_window_k: String(initial.context_window_k),
    max_tokens: String(initial.max_tokens),
    ...Object.fromEntries(
      Object.entries(initial.retry).flatMap(([layer, rule]) => [
        [layer + "_attempts", String(rule.attempts)],
        [layer + "_interval_ms", String(rule.interval_ms)],
      ]),
    ),
  }));
  const [error, setError] = useState<string | null>(null);
  function numberField(key: string, en: string, ko: string, hint: string) {
    return (
      <Field label={t(en, ko)} hint={hint}>
        <input
          inputMode={key.endsWith("attempts") ? "text" : "numeric"}
          value={numbers[key]}
          onChange={(e) => {
            setNumbers({ ...numbers, [key]: e.target.value });
            setError(null);
          }}
        />
      </Field>
    );
  }
  return (
    <form
      className="form-stack"
      onSubmit={(event) => {
        event.preventDefault();
        if (disabled) return;
        if (
          Object.values(numbers).some(
            (value) =>
              !/^-?\d+$/.test(value) || !Number.isSafeInteger(Number(value)),
          )
        ) {
          setError("number");
          return;
        }
        const candidate: AIModelProfile = {
          ...draft,
          rate_per_second: Number(numbers.rate_per_second),
          rate_per_minute: Number(numbers.rate_per_minute),
          context_window_k: Number(numbers.context_window_k),
          max_tokens: Number(numbers.max_tokens),
          retry: {
            connect: {
              attempts: Number(numbers.connect_attempts),
              interval_ms: Number(numbers.connect_interval_ms),
            },
            empty: {
              attempts: Number(numbers.empty_attempts),
              interval_ms: Number(numbers.empty_interval_ms),
            },
            stream: {
              attempts: Number(numbers.stream_attempts),
              interval_ms: Number(numbers.stream_interval_ms),
            },
          },
        };
        const issue = profileIssue(candidate, profiles);
        setError(issue);
        if (!issue) onSave(candidate);
      }}
    >
      {error && (
        <Notice tone="danger">
          <div>
            {t("Check the invalid field:", "잘못된 필드를 확인하세요:")}{" "}
            <code>{error}</code>
            <p>
              {error === "name"
                ? t(
                    "Use a unique, nonblank name of 1–120 characters without surrounding whitespace or control characters.",
                    "앞뒤 공백이나 제어 문자 없이 고유한 이름을 1~120자로 입력하세요.",
                  )
                : error === "base_url"
                  ? t(
                      "Use an absolute HTTP(S) URL with a valid host/port, without credentials, query, fragment, whitespace, backslash or encoded authority.",
                      "올바른 호스트/포트의 절대 HTTP(S) URL을 입력하세요. 자격 증명, 쿼리, 프래그먼트, 공백, 역슬래시, 인코딩된 권한 부분은 사용할 수 없습니다.",
                    )
                  : error === "credential_env"
                    ? t(
                        "Use an uppercase environment-variable name, never a key value (A–Z, 0–9, underscore; starts with a letter).",
                        "키 값이 아닌 대문자 환경 변수 이름을 입력하세요 (A~Z, 0~9, 밑줄, 첫 글자는 문자).",
                      )
                    : error === "model"
                      ? t(
                          "Enter a literal model ID of 1–200 characters without surrounding whitespace or control characters.",
                          "앞뒤 공백이나 제어 문자 없이 모델 ID를 1~200자로 입력하세요.",
                        )
                      : t(
                          "Enter finite whole numbers within the displayed ranges; blank or malformed input is not zero.",
                          "표시된 범위의 유한한 정수를 입력하세요. 빈 값이나 잘못된 입력은 0이 아닙니다.",
                        )}
            </p>
          </div>
        </Notice>
      )}
      <code aria-label={t("Profile ID", "프로필 ID")}>{draft.id}</code>
      <fieldset className="page-fieldset form-stack" disabled={disabled}>
        <Field label={t("Profile name", "프로필 이름")}>
          <input
            value={draft.name}
            onChange={(e) => setDraft({ ...draft, name: e.target.value })}
            required
            autoComplete="off"
          />
        </Field>
        <Field
          label={t("Protocol", "프로토콜")}
          hint={t(
            "Protocol is not a vendor. Enter the model ID manually. Changing away from Chat Completions clears its output-field override.",
            "프로토콜은 공급자가 아닙니다. 모델 ID를 직접 입력하세요. Chat Completions에서 다른 프로토콜로 변경하면 출력 필드 재정의가 지워집니다.",
          )}
        >
          <select
            value={draft.format}
            onChange={(e) =>
              setDraft({
                ...draft,
                format: e.target.value as AIProtocol,
                max_tokens_field:
                  e.target.value === "openai" ? draft.max_tokens_field : "",
              })
            }
          >
            <option value="openai">OpenAI Chat Completions</option>
            <option value="openai-responses">OpenAI Responses</option>
            <option value="anthropic">Anthropic Messages</option>
          </select>
        </Field>
        <Field label={t("Model ID", "모델 ID")}>
          <input
            value={draft.model}
            onChange={(e) => setDraft({ ...draft, model: e.target.value })}
            required
            autoComplete="off"
            spellCheck={false}
          />
        </Field>
        <Field
          label={t("Base URL", "기본 URL")}
          hint={t(
            "Optional HTTP(S) endpoint metadata; never contacted.",
            "선택 사항인 HTTP(S) 엔드포인트 정보이며 연결하지 않습니다.",
          )}
        >
          <input
            value={draft.base_url}
            onChange={(e) => setDraft({ ...draft, base_url: e.target.value })}
            autoComplete="off"
            spellCheck={false}
          />
        </Field>
        <Field
          label={t("Credential environment variable", "자격 증명 환경 변수")}
          hint={t(
            "Optional variable name only, not an API key. No environment values are read.",
            "API 키가 아닌 변수 이름만 입력하세요 (선택). 환경 변수 값은 읽지 않습니다.",
          )}
        >
          <input
            value={draft.credential_env}
            onChange={(e) =>
              setDraft({ ...draft, credential_env: e.target.value })
            }
            maxLength={64}
            autoComplete="off"
            spellCheck={false}
          />
        </Field>
        <details className="ais-disclosure">
          <summary>{t("Advanced settings", "고급 설정")}</summary>
          <div className="form-stack">
            <div className="form-grid">
              {numberField(
                "rate_per_second",
                "Requests per second",
                "초당 요청 수",
                t(
                  "0 = no profile-specific limit; otherwise 1–1,000,000.",
                  "0 = 프로필별 제한 없음, 그 외 1~1,000,000.",
                ),
              )}
              {numberField(
                "rate_per_minute",
                "Requests per minute",
                "분당 요청 수",
                t(
                  "0 = no profile-specific limit; otherwise 1–1,000,000.",
                  "0 = 프로필별 제한 없음, 그 외 1~1,000,000.",
                ),
              )}
              {numberField(
                "context_window_k",
                "Context capacity (K tokens)",
                "컨텍스트 용량 (K 토큰)",
                t(
                  "0 = reference default 200K; otherwise 32–1000K. Total context, not output.",
                  "0 = 참조 기본값 200K, 그 외 32~1000K. 출력이 아닌 전체 컨텍스트입니다.",
                ),
              )}
              {numberField(
                "max_tokens",
                "Output token limit",
                "출력 토큰 제한",
                t(
                  "0 = omit output cap; up to 1,000,000.",
                  "0 = 출력 제한 생략, 최대 1,000,000.",
                ),
              )}
            </div>
            <Field label={t("Streaming", "스트리밍")}>
              <input
                type="checkbox"
                checked={draft.streaming}
                onChange={(e) =>
                  setDraft({ ...draft, streaming: e.target.checked })
                }
              />
            </Field>
            <Field
              label={t("Output token field", "출력 토큰 필드")}
              hint={t(
                "Only Chat Completions supports this override. Switching away clears it; empty uses the protocol default (max_tokens for Chat Completions).",
                "Chat Completions만 이 재정의를 지원합니다. 다른 프로토콜로 변경하면 지워집니다. 빈 값은 프로토콜 기본값을 사용합니다 (Chat Completions: max_tokens).",
              )}
            >
              <select
                disabled={draft.format !== "openai"}
                value={draft.max_tokens_field}
                onChange={(e) =>
                  setDraft({
                    ...draft,
                    max_tokens_field: e.target
                      .value as AIModelProfile["max_tokens_field"],
                  })
                }
              >
                <option value="">
                  {t("Protocol default", "프로토콜 기본값")}
                </option>
                <option value="max_completion_tokens">
                  max_completion_tokens
                </option>
              </select>
            </Field>
            <div className="form-grid">
              <Field
                label={t("Thinking", "사고 모드")}
                hint={t(
                  "Independent of reasoning effort.",
                  "추론 강도와 별개입니다.",
                )}
              >
                <select
                  value={draft.thinking_type}
                  onChange={(e) =>
                    setDraft({
                      ...draft,
                      thinking_type: e.target
                        .value as AIModelProfile["thinking_type"],
                    })
                  }
                >
                  <option value="">{t("Unspecified", "미지정")}</option>
                  <option value="disabled">{t("Disabled", "비활성화")}</option>
                  <option value="enabled">{t("Enabled", "활성화")}</option>
                </select>
              </Field>
              <Field label={t("Reasoning effort", "추론 강도")}>
                <select
                  value={draft.reasoning_effort}
                  onChange={(e) =>
                    setDraft({
                      ...draft,
                      reasoning_effort: e.target
                        .value as AIModelProfile["reasoning_effort"],
                    })
                  }
                >
                  <option value="">{t("Unspecified", "미지정")}</option>
                  {["low", "medium", "high", "xhigh", "max"].map((value, i) => (
                    <option key={value} value={value}>
                      {t(
                        value,
                        ["낮음", "보통", "높음", "매우 높음", "최대"][i],
                      )}
                    </option>
                  ))}
                </select>
              </Field>
            </div>
          </div>
        </details>
        <details className="ais-disclosure">
          <summary>{t("Retry policy", "재시도 정책")}</summary>
          <div className="form-stack">
            <p className="muted">
              {t(
                "Stored policy only, not a retry engine. Attempts: -1 disables, 0 inherits, 1–20 sets a count. Interval: 0 inherits the strategy; maximum 3,600,000 ms.",
                "저장된 정책일 뿐 재시도 엔진이 아닙니다. 횟수: -1 비활성화, 0 상속, 1~20 횟수 지정. 간격: 0 전략 상속, 최대 3,600,000 ms.",
              )}
            </p>
            {(["connect", "empty", "stream"] as const).map((layer, i) => (
              <div className="form-grid" key={layer}>
                {numberField(
                  layer + "_attempts",
                  ["Connect", "Empty", "Stream"][i] + " attempts",
                  ["연결", "빈 응답", "스트림"][i] + " 재시도 횟수",
                  "-1 … 20",
                )}
                {numberField(
                  layer + "_interval_ms",
                  ["Connect", "Empty", "Stream"][i] + " interval (ms)",
                  ["연결", "빈 응답", "스트림"][i] + " 재시도 간격 (ms)",
                  "0 … 3,600,000 ms",
                )}
              </div>
            ))}
          </div>
        </details>
      </fieldset>
      <div className="button-row">
        <Button type="submit" variant="primary" disabled={disabled}>
          {t("Save profile", "프로필 저장")}
        </Button>
        <Button onClick={onClose}>{t("Close", "닫기")}</Button>
      </div>
    </form>
  );
}
