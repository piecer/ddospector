import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { Crosshair, Plus } from "lucide-react";
import {
  Badge,
  Button,
  DataTable,
  Dialog,
  EmptyState,
  Field,
  Notice,
  PageHeader,
  Panel,
} from "../../components/ui";
import { api } from "../../lib/api";
import type { PageProps, TargetInput } from "../../lib/contracts";
import { choose, formatDate } from "../../lib/i18n";
import { useTargetReadback } from "../ai/useTargetReadback";
import { useDraft } from "./use-draft";
import { validAddress, validName } from "./validation";

export function TargetsPage({
  data,
  locale,
  refresh,
  targetSelection,
}: PageProps) {
  const c = (en: string, ko: string) => choose(locale, en, ko);
  const [open, setOpen] = useState(false);
  const readback = useTargetReadback(targetSelection, data);
  const selectedRow = useRef<HTMLTableRowElement>(null);
  useEffect(() => {
    if (
      !open &&
      (readback.state === "receipt-confirmed" ||
        readback.state === "current-only")
    )
      selectedRow.current?.focus();
  }, [open, readback.state, readback.target]);
  // Workspace data never overwrites a separately inspected selected record.
  const targets = targetSelection
    ? [
        ...data.targets.filter((t) => t.id !== targetSelection.id),
        ...(readback.target ? [readback.target] : []),
      ]
    : data.targets;
  const readbackText = {
    loading: c("Reading current target inventory…", "현재 대상 목록 읽는 중…"),
    "receipt-confirmed": c(
      "Fresh record matches the saved receipt and revision floor.",
      "새로 읽은 레코드가 저장 영수증 및 최소 리비전과 일치합니다.",
    ),
    "current-only": c(
      "Current record only — no historical saved-receipt comparison.",
      "현재 레코드만 표시 — 이전 저장 영수증과 비교하지 않았습니다.",
    ),
    mismatch: targetSelection?.expectation
      ? c(
          "Readback discrepancy; the saved receipt remains unchanged. Do not recreate.",
          "다시 읽기 불일치. 저장 영수증은 그대로 유지됩니다. 다시 생성하지 마세요.",
        )
      : c(
          "Selected ID is absent from the current inventory. No historical save comparison is available.",
          "현재 목록에 선택한 ID가 없습니다. 이전 저장 기록과 비교할 수 없습니다.",
        ),
    unavailable: c(
      "Readback unavailable; any last inspected row is stale/unverified. A saved receipt is not erased. Retry GET only.",
      "다시 읽기 불가. 마지막으로 읽은 행은 오래된 미검증 상태입니다. 저장 영수증은 유지됩니다. GET만 재시도하세요.",
    ),
    stale: c(
      "Last inspected record — stale/unverified pending a fresh read.",
      "마지막으로 읽은 레코드 — 새로 읽기 전 오래된 미검증 상태입니다.",
    ),
  };
  const [draft, setDraft] = useState<TargetInput>({
    name: "",
    address: "",
    kind: "DUT",
  });
  const [invalid, setInvalid] = useState<"name" | "address" | null>(null);
  const atLimit = data.targets.length >= 100;
  const mutation = useDraft(refresh, () => {
    setOpen(false);
    setDraft({ name: "", address: "", kind: "DUT" });
    setInvalid(null);
  });
  async function save(event: FormEvent) {
    event.preventDefault();
    if (mutation.busy) return;
    if (!mutation.saved) {
      const issue = !validName(draft.name)
        ? "name"
        : !validAddress(draft.address)
          ? "address"
          : null;
      setInvalid(issue);
      if (issue || atLimit) return;
    }
    await mutation.submit(() =>
      api.createTarget({ ...draft, name: draft.name.trim() }),
    );
  }
  return (
    <div className="page-stack lab-page">
      <PageHeader
        eyebrow={c("Lab configuration", "실험실 구성")}
        title={c("Targets", "시험 대상")}
        description={c(
          "Define the system under test and its traffic destination. Registration saves metadata only.",
          "시험 대상과 트래픽 수신 대상을 정의합니다. 등록 시 메타데이터만 저장합니다.",
        )}
        actions={
          <Button
            variant="primary"
            disabled={atLimit || mutation.busy}
            onClick={() => setOpen(true)}
          >
            <Plus size={16} aria-hidden="true" />
            {c("Add target", "시험 대상 추가")}
          </Button>
        }
      />
      {atLimit && (
        <Notice tone="warning">
          {c(
            "Target limit reached (100 drafts).",
            "시험 대상 한도에 도달했습니다(초안 100개).",
          )}
        </Notice>
      )}
      <Notice>
        {c(
          "Draft inventory only. No address is contacted, verified, or authorized for traffic.",
          "초안 목록입니다. 주소에 접속하거나 검증하지 않으며 트래픽 전송 권한을 부여하지 않습니다.",
        )}
      </Notice>
      {targetSelection && (
        <section
          aria-label={c("Selected target readback", "선택 대상 다시 읽기")}
        >
          <p
            data-testid="target-readback-status"
            data-readback={readback.state}
            role="status"
          >
            {readbackText[readback.state]}
          </p>
          <p className="mono">{targetSelection.id}</p>
          <Button onClick={readback.refresh} disabled={readback.pending}>
            {c(
              "Read selected target again (GET only)",
              "선택 대상 다시 읽기 (GET 전용)",
            )}
          </Button>
          {readback.pending && (
            <Button onClick={readback.cancel}>
              {c("Cancel target read", "대상 읽기 취소")}
            </Button>
          )}
        </section>
      )}
      <Panel
        title={c("Target inventory", "시험 대상 목록")}
        actions={
          <Badge>
            {targets.length} {c("drafts", "개 초안")}
          </Badge>
        }
      >
        {targets.length === 0 ? (
          <EmptyState
            icon={<Crosshair size={28} />}
            title={c(
              "No target drafts yet",
              "등록된 시험 대상 초안이 없습니다",
            )}
            description={c(
              "Add a DUT or SINK address to prepare a campaign draft. No connection is made.",
              "캠페인 초안을 준비하려면 DUT 또는 SINK 주소를 추가하세요. 연결은 수행하지 않습니다.",
            )}
          />
        ) : (
          <DataTable label={c("Target drafts", "시험 대상 초안")}>
            <table className="table">
              <thead>
                <tr>
                  <th>ID</th>
                  <th>{c("Name", "이름")}</th>
                  <th>{c("Address", "주소")}</th>
                  <th>{c("Role", "역할")}</th>
                  <th>{c("Status", "상태")}</th>
                  <th>{c("Created", "생성 일시")}</th>
                </tr>
              </thead>
              <tbody>
                {targets.map((target) => (
                  <tr
                    key={target.id}
                    data-testid={`target-row-${target.id}`}
                    data-selected={
                      targetSelection?.id === target.id ? "true" : "false"
                    }
                    ref={
                      targetSelection?.id === target.id
                        ? selectedRow
                        : undefined
                    }
                    tabIndex={
                      targetSelection?.id === target.id ? -1 : undefined
                    }
                    style={
                      targetSelection?.id === target.id
                        ? {
                            outline: "2px solid currentColor",
                            outlineOffset: "-2px",
                          }
                        : undefined
                    }
                  >
                    <td className="mono">{target.id}</td>
                    <td>{target.name}</td>
                    <td className="mono">{target.address}</td>
                    <td>{target.kind}</td>
                    <td>
                      <Badge tone="warning">
                        {c("Draft · not verified", "초안 · 미검증")}{" "}
                        <span className="mono">{target.status}</span>
                      </Badge>
                    </td>
                    <td>
                      {targetSelection?.id === target.id
                        ? target.created_at
                        : formatDate(target.created_at, locale)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </DataTable>
        )}
      </Panel>
      <div className="grid-two">
        <Panel title={c("DUT · device under test", "DUT · 시험 대상 장치")}>
          <p className="muted">
            {c(
              "The system whose policy or behavior a future campaign will evaluate.",
              "향후 캠페인에서 정책이나 동작을 평가할 시스템입니다.",
            )}
          </p>
        </Panel>
        <Panel
          title={c("SINK · traffic destination", "SINK · 트래픽 수신 대상")}
        >
          <p className="muted">
            {c(
              "The intended receiving endpoint. A saved address is not proof of ownership or permission.",
              "예정된 수신 지점입니다. 주소 저장만으로 소유권이나 권한이 입증되지 않습니다.",
            )}
          </p>
        </Panel>
      </div>
      <Dialog
        open={open}
        recoveryOnly={mutation.saved}
        title={c("Add target draft", "시험 대상 초안 추가")}
        onClose={() => setOpen(false)}
      >
        <form
          className="form-stack"
          onSubmit={save}
          noValidate
          aria-busy={mutation.busy}
        >
          <p className="muted">
            {c(
              "All fields are required. Name: up to 120 characters; address: up to 255. Do not include a URL, port, or credentials.",
              "모든 항목은 필수입니다. 이름은 최대 120자, 주소는 최대 255자입니다. URL, 포트, 인증 정보를 포함하지 마세요.",
            )}
          </p>
          {invalid && (
            <Notice tone="danger">
              <span id="target-validation">
                {invalid === "name"
                  ? c(
                      "Name must contain 1–120 characters, without control characters.",
                      "이름은 제어 문자 없이 1~120자로 입력하세요.",
                    )
                  : c(
                      "Enter a valid IP address or hostname (up to 255 characters).",
                      "올바른 IP 주소 또는 호스트 이름을 입력하세요(최대 255자).",
                    )}
              </span>
            </Notice>
          )}
          {mutation.error && (
            <Notice tone="danger">
              {mutation.error === "save"
                ? c(
                    "Could not save the draft. Check the local API and retry; your inputs are preserved.",
                    "초안을 저장하지 못했습니다. 로컬 API를 확인하고 다시 시도하세요. 입력 내용은 유지됩니다.",
                  )
                : c(
                    "Draft saved, but the workspace could not refresh. Retry refresh without creating another draft.",
                    "초안은 저장되었지만 워크스페이스를 새로 고치지 못했습니다. 초안을 다시 만들지 않고 새로 고침만 재시도하세요.",
                  )}
            </Notice>
          )}
          <Field label={c("Name", "이름")}>
            <input
              required
              maxLength={120}
              disabled={mutation.busy || mutation.saved}
              aria-invalid={invalid === "name"}
              aria-describedby={
                invalid === "name" ? "target-validation" : undefined
              }
              value={draft.name}
              onChange={(event) =>
                setDraft({ ...draft, name: event.target.value })
              }
            />
          </Field>
          <Field
            label={c("IP address or hostname", "IP 주소 또는 호스트 이름")}
          >
            <input
              required
              maxLength={255}
              spellCheck={false}
              autoCapitalize="none"
              disabled={mutation.busy || mutation.saved}
              aria-invalid={invalid === "address"}
              aria-describedby={
                invalid === "address" ? "target-validation" : undefined
              }
              value={draft.address}
              onChange={(event) =>
                setDraft({ ...draft, address: event.target.value })
              }
            />
          </Field>
          <Field label={c("Role", "역할")}>
            <select
              disabled={mutation.busy || mutation.saved}
              value={draft.kind}
              onChange={(event) =>
                setDraft({
                  ...draft,
                  kind: event.target.value as TargetInput["kind"],
                })
              }
            >
              <option value="DUT">
                {c("DUT — device under test", "DUT — 시험 대상 장치")}
              </option>
              <option value="SINK">
                {c("SINK — traffic destination", "SINK — 트래픽 수신 대상")}
              </option>
            </select>
          </Field>
          <div className="button-row">
            <Button onClick={() => setOpen(false)}>{c("Close", "닫기")}</Button>
            <Button
              type="submit"
              variant="primary"
              disabled={mutation.busy || (atLimit && !mutation.saved)}
            >
              {mutation.busy
                ? c("Saving…", "저장 중…")
                : mutation.saved
                  ? c("Retry refresh", "새로 고침 재시도")
                  : c("Save draft", "초안 저장")}
            </Button>
          </div>
        </form>
      </Dialog>
    </div>
  );
}
