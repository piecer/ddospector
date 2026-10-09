import { useId, useRef, useState } from "react";
import { LockKeyhole, RefreshCw } from "lucide-react";
import { Button, Notice } from "../../components/ui";
import type { Locale } from "../../lib/contracts";
import { choose } from "../../lib/i18n";
import "./operations.css";

export function LockedAction({
  label,
  reason,
}: {
  label: string;
  reason: string;
}) {
  const id = useId();
  return (
    <div className="operations-locked-action">
      <Button disabled aria-describedby={id}>
        <LockKeyhole size={15} aria-hidden="true" />
        {label}
      </Button>
      <p id={id} className="muted">
        {reason}
      </p>
    </div>
  );
}

export function RefreshWorkspace({
  locale,
  refresh,
  disabled = false,
}: {
  locale: Locale;
  refresh: () => Promise<void>;
  disabled?: boolean;
}) {
  const t = (en: string, ko: string) => choose(locale, en, ko);
  const [state, setState] = useState<"idle" | "pending" | "error" | "ready">(
    "idle",
  );
  const pending = useRef(false);
  async function reload() {
    if (pending.current || disabled) return;
    pending.current = true;
    setState("pending");
    try {
      await refresh();
      setState("ready");
    } catch {
      setState("error");
    } finally {
      pending.current = false;
    }
  }
  return (
    <div className="operations-refresh">
      <Button
        variant="ghost"
        disabled={disabled || state === "pending"}
        onClick={() => void reload()}
      >
        <RefreshCw size={15} aria-hidden="true" />
        {state === "pending"
          ? t("Refreshing…", "새로고침 중…")
          : state === "error"
            ? t("Retry refresh", "새로고침 재시도")
            : t("Refresh workspace", "워크스페이스 새로고침")}
      </Button>
      {(state === "pending" || state === "ready") && (
        <span role="status" className="muted">
          {state === "pending"
            ? t(
                "Loading the latest workspace snapshot…",
                "최신 워크스페이스 스냅샷을 불러오는 중…",
              )
            : t("Workspace refreshed.", "워크스페이스를 새로고침했습니다.")}
        </span>
      )}
      {state === "error" && (
        <Notice tone="danger">
          {t(
            "Could not refresh. Displayed data may be stale. Retry when the local API is available.",
            "새로고침하지 못했습니다. 표시된 데이터가 오래되었을 수 있습니다. 로컬 API가 사용 가능할 때 다시 시도하세요.",
          )}
        </Notice>
      )}
    </div>
  );
}
