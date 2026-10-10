import { useRef, useState, type FormEvent } from "react";
import { FolderKanban } from "lucide-react";
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
import type { PageProps } from "../../lib/contracts";
import { choose, formatDate, text } from "../../lib/i18n";
import { RefreshWorkspace } from "./common";

export function CampaignsPage({ data, locale, navigate, refresh }: PageProps) {
  const t = (en: string, ko: string) => choose(locale, en, ko);
  const ready = data.targets.length > 0 && data.profiles.length > 0;
  const atLimit = data.campaigns.length >= 100;
  const limitMessage = t(
    "The local limit of 100 campaign drafts has been reached. Additional drafts cannot be saved.",
    "로컬 캠페인 초안 한도인 100개에 도달했습니다. 초안을 더 저장할 수 없습니다.",
  );
  const failureMessage = t(
    "The draft could not be saved. Your input is preserved; check the workspace and try again.",
    "초안을 저장하지 못했습니다. 입력 내용은 유지됩니다. 워크스페이스를 확인하고 다시 시도하세요.",
  );
  const [open, setOpen] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const selected = data.campaigns.find(
    (campaign) => campaign.id === selectedId,
  );
  const targetName = (id: string) =>
    data.targets.find((target) => target.id === id)?.name ??
    t("Unavailable target", "대상 정보 없음");
  const profileName = (id: string) => {
    const profile = data.profiles.find((item) => item.id === id);
    return profile
      ? text(profile.name, locale)
      : t("Unavailable profile", "프로필 정보 없음");
  };
  const [name, setName] = useState("");
  const [objective, setObjective] = useState("");
  const [targetId, setTargetId] = useState("");
  const [profileId, setProfileId] = useState("");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [saveFailed, setSaveFailed] = useState(false);
  const [staleList, setStaleList] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [validation, setValidation] = useState<"text" | "reference" | null>(
    null,
  );
  const submitting = useRef(false);
  async function retryRefresh() {
    if (refreshing) return;
    setRefreshing(true);
    try {
      await refresh();
      setStaleList(false);
    } catch {
      setStaleList(true);
    } finally {
      setRefreshing(false);
    }
  }
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting.current || atLimit || staleList) return;
    setValidation(null);
    setSaveFailed(false);
    if (
      !name.trim() ||
      name.trim().length > 120 ||
      !objective.trim() ||
      objective.trim().length > 2000
    ) {
      setValidation("text");
      return;
    }
    if (
      !data.targets.some((target) => target.id === targetId) ||
      !data.profiles.some((profile) => profile.id === profileId)
    ) {
      setValidation("reference");
      return;
    }
    submitting.current = true;
    setSaving(true);
    try {
      await api.createCampaign({
        name: name.trim(),
        objective: objective.trim(),
        target_id: targetId,
        profile_id: profileId,
      });
      setSaved(true);
      setOpen(false);
      setName("");
      setObjective("");
      setTargetId("");
      setProfileId("");
      try {
        await refresh();
      } catch {
        setStaleList(true);
      }
    } catch {
      setSaveFailed(true);
    } finally {
      submitting.current = false;
      setSaving(false);
    }
  }
  return (
    <div className="page-stack operations-page">
      <PageHeader
        eyebrow={t("Workspace / Planning", "워크스페이스 / 계획")}
        title={t("Campaigns", "캠페인")}
        description={t(
          "Define the objective, target, and profile. Save a plan, not an execution.",
          "목표, 대상, 프로필을 정의합니다. 실행이 아닌 계획을 저장합니다.",
        )}
        actions={
          <Button
            variant="primary"
            disabled={!ready || atLimit || staleList || saving}
            onClick={() => {
              setSaved(false);
              setSaveFailed(false);
              setValidation(null);
              setOpen(true);
            }}
          >
            {t("New campaign", "새 캠페인")}
          </Button>
        }
      />
      <Notice>
        {t(
          "Versioned scenario definitions are separate from these campaign drafts and do not authorize execution.",
          "버전별 시나리오 정의는 캠페인 초안과 별개이며 실행을 승인하지 않습니다.",
        )}
        <div className="button-row">
          <Button onClick={() => navigate("profiles")}>
            {t("Open scenario library", "시나리오 라이브러리 열기")}
          </Button>
        </div>
      </Notice>
      {saved && !saving && (
        <div role="status">
          <Notice tone="success">
            {t(
              "Campaign draft saved. No execution was started.",
              "캠페인 초안을 저장했습니다. 실행은 시작되지 않았습니다.",
            )}
          </Notice>
        </div>
      )}
      {saving && !open && (
        <div role="status">
          <Notice>
            {saved
              ? t(
                  "Refreshing saved campaign drafts…",
                  "저장된 캠페인 초안을 새로고침하는 중…",
                )
              : t(
                  "Saving the draft. Closing the dialog does not cancel the request.",
                  "초안을 저장하는 중입니다. 대화상자를 닫아도 요청은 취소되지 않습니다.",
                )}
          </Notice>
        </div>
      )}
      {saveFailed && !open && (
        <Notice tone="danger">
          {failureMessage}
          <div className="button-row">
            <Button onClick={() => setOpen(true)}>
              {t("Resume draft", "초안 이어서 작성")}
            </Button>
          </div>
        </Notice>
      )}
      {staleList && (
        <Notice tone="danger">
          {t(
            "The draft was saved, but the list could not be refreshed. Refresh the list before creating another draft.",
            "초안은 저장되었지만 목록을 새로고침하지 못했습니다. 다른 초안을 만들기 전에 목록을 새로고침하세요.",
          )}
          <div className="button-row">
            <Button disabled={refreshing} onClick={() => void retryRefresh()}>
              {refreshing
                ? t("Refreshing…", "새로고침 중…")
                : t("Retry refresh", "새로고침 재시도")}
            </Button>
          </div>
        </Notice>
      )}
      {!staleList && (
        <RefreshWorkspace locale={locale} refresh={refresh} disabled={saving} />
      )}
      <Notice>
        {t(
          "Drafts are stored locally. Live execution is disabled on the server.",
          "초안은 로컬에 저장됩니다. 서버에서 라이브 실행이 비활성화되어 있습니다.",
        )}
      </Notice>
      {!ready && (
        <Notice tone="warning">
          {t(
            "Add a target draft and a profile template before creating a campaign.",
            "캠페인을 만들려면 대상 초안과 프로필 템플릿이 필요합니다.",
          )}
          <div className="button-row">
            <Button onClick={() => navigate("targets")}>
              {t("Configure targets", "대상 구성")}
            </Button>
            <Button onClick={() => navigate("profiles")}>
              {t("Browse profiles", "프로필 보기")}
            </Button>
          </div>
        </Notice>
      )}
      {atLimit && <Notice tone="warning">{limitMessage}</Notice>}
      <Panel
        title={t("Campaign drafts", "캠페인 초안")}
        actions={<Badge>{t("Local drafts", "로컬 초안")}</Badge>}
      >
        {data.campaigns.length === 0 ? (
          <EmptyState
            icon={<FolderKanban size={30} />}
            title={t("No campaign drafts yet", "캠페인 초안이 없습니다")}
            description={t(
              "Start with an owned lab target and an available profile template. No traffic will be generated.",
              "실험실에서 관리하는 대상과 사용 가능한 프로필 템플릿으로 시작하세요. 트래픽은 생성되지 않습니다.",
            )}
          />
        ) : (
          <DataTable label={t("Campaign draft list", "캠페인 초안 목록")}>
            <table className="table operations-table">
              <thead>
                <tr>
                  <th scope="col">{t("Campaign", "캠페인")}</th>
                  <th scope="col">{t("Target", "대상")}</th>
                  <th scope="col">{t("Profile", "프로필")}</th>
                  <th scope="col">{t("Status", "상태")}</th>
                  <th scope="col">{t("Created", "생성 시각")}</th>
                </tr>
              </thead>
              <tbody>
                {data.campaigns.map((campaign) => (
                  <tr key={campaign.id}>
                    <td>
                      <button
                        className="text-link operations-name"
                        type="button"
                        onClick={() => setSelectedId(campaign.id)}
                      >
                        {campaign.name}
                      </button>
                      <small className="mono muted">{campaign.id}</small>
                    </td>
                    <td>{targetName(campaign.target_id)}</td>
                    <td>{profileName(campaign.profile_id)}</td>
                    <td>
                      <Badge>{t("Draft", "초안")}</Badge>
                    </td>
                    <td>
                      <time dateTime={campaign.created_at}>
                        {formatDate(campaign.created_at, locale)}
                      </time>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </DataTable>
        )}
      </Panel>
      <Dialog
        open={Boolean(selected)}
        title={t("Campaign draft details", "캠페인 초안 상세")}
        onClose={() => setSelectedId(null)}
      >
        {selected && (
          <div className="form-stack">
            <Badge>{t("Draft only", "초안 전용")}</Badge>
            <h3 className="operations-wrap">{selected.name}</h3>
            <dl className="detail-list">
              <dt>{t("Campaign ID", "캠페인 ID")}</dt>
              <dd className="mono">{selected.id}</dd>
              <dt>{t("Objective", "목표")}</dt>
              <dd className="operations-prose">{selected.objective}</dd>
              <dt>{t("Target", "대상")}</dt>
              <dd>
                {targetName(selected.target_id)}
                <small className="mono muted">{selected.target_id}</small>
              </dd>
              <dt>{t("Profile", "프로필")}</dt>
              <dd>
                {profileName(selected.profile_id)}
                <small className="mono muted">{selected.profile_id}</small>
              </dd>
              <dt>{t("Created", "생성 시각")}</dt>
              <dd>
                <time dateTime={selected.created_at}>
                  {formatDate(selected.created_at, locale)}
                </time>
              </dd>
            </dl>
            <Notice tone="warning">
              <span id="campaign-run-reason">
                {t(
                  "This draft grants no execution authority. The server does not allow live runs.",
                  "이 초안은 실행을 승인하지 않습니다. 서버에서 라이브 실행을 허용하지 않습니다.",
                )}
              </span>
            </Notice>
            <div className="button-row">
              <Button disabled aria-describedby="campaign-run-reason">
                {t("Start run", "실행 시작")}
              </Button>
              <Button onClick={() => setSelectedId(null)}>
                {t("Close", "닫기")}
              </Button>
            </div>
          </div>
        )}
      </Dialog>
      <Dialog
        open={open}
        title={t("New campaign draft", "새 캠페인 초안")}
        onClose={() => setOpen(false)}
      >
        <form
          className="form-stack"
          onSubmit={submit}
          aria-busy={saving}
          noValidate
        >
          <Notice>
            {t(
              "Saving only records your intent. It does not authorize or start a run.",
              "저장은 계획만 기록합니다. 실행을 승인하거나 시작하지 않습니다.",
            )}
          </Notice>
          {saveFailed && <Notice tone="danger">{failureMessage}</Notice>}
          {atLimit && <Notice tone="warning">{limitMessage}</Notice>}
          {saving && (
            <p className="muted">
              {t(
                "Closing this dialog does not cancel a request already sent to the server.",
                "이 대화상자를 닫아도 서버로 이미 전송된 요청은 취소되지 않습니다.",
              )}
            </p>
          )}
          {validation && (
            <Notice tone="danger">
              {validation === "text"
                ? t(
                    "Enter a name of 1–120 characters and an objective of 1–2,000 characters.",
                    "이름은 1~120자, 목표는 1~2,000자로 입력하세요.",
                  )
                : t(
                    "Select a target and a profile that exist in the current workspace.",
                    "현재 워크스페이스에 존재하는 대상과 프로필을 선택하세요.",
                  )}
            </Notice>
          )}
          <Field label={t("Campaign name", "캠페인 이름")}>
            <input
              required
              maxLength={120}
              value={name}
              onChange={(event) => setName(event.target.value)}
              disabled={saving}
            />
          </Field>
          <Field label={t("Objective", "목표")}>
            <textarea
              required
              maxLength={2000}
              rows={4}
              value={objective}
              onChange={(event) => setObjective(event.target.value)}
              disabled={saving}
            />
          </Field>
          <div className="form-grid">
            <Field label={t("Target", "대상")}>
              <select
                required
                value={targetId}
                onChange={(event) => setTargetId(event.target.value)}
                disabled={saving}
              >
                <option value="">{t("Choose a target", "대상 선택")}</option>
                {data.targets.map((target) => (
                  <option key={target.id} value={target.id}>
                    {target.name} · {target.address}
                  </option>
                ))}
              </select>
            </Field>
            <Field label={t("Profile template", "프로필 템플릿")}>
              <select
                required
                value={profileId}
                onChange={(event) => setProfileId(event.target.value)}
                disabled={saving}
              >
                <option value="">{t("Choose a profile", "프로필 선택")}</option>
                {data.profiles.map((profile) => (
                  <option key={profile.id} value={profile.id}>
                    {text(profile.name, locale)} · {profile.engine}
                  </option>
                ))}
              </select>
            </Field>
          </div>
          <div className="button-row">
            <Button
              variant="primary"
              type="submit"
              disabled={saving || atLimit}
            >
              {saving
                ? t("Saving draft…", "초안 저장 중…")
                : t("Save draft", "초안 저장")}
            </Button>
            <Button onClick={() => setOpen(false)}>
              {saving
                ? t("Close dialog", "대화상자 닫기")
                : t("Cancel", "취소")}
            </Button>
          </div>
        </form>
      </Dialog>
    </div>
  );
}
