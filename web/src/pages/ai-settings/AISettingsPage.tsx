import "./ai-settings.css";
import { useCallback, useEffect, useRef, useState } from "react";
import type { PageProps } from "../../lib/contracts";
import {
  Badge,
  Button,
  Dialog,
  EmptyState,
  Notice,
  PageHeader,
  Panel,
} from "../../components/ui";
import { choose } from "../../lib/i18n";
import { aiSettingsAPI } from "./client";
import type {
  AIModelProfile,
  AISettingsInput,
  AISettingsSnapshot,
} from "./types";
import { newProfile, ProfileEditor } from "./ProfileEditor";
import { Bindings, type BindingsValue } from "./Bindings";
export function AISettingsPage({ locale }: PageProps) {
  const t = (en: string, ko: string) => choose(locale, en, ko);
  const [snapshot, setSnapshot] = useState<AISettingsSnapshot | null>(null);
  const [draft, setDraft] = useState<AIModelProfile | null>(null);
  const [deleting, setDeleting] = useState<AIModelProfile | null>(null);
  const [bindings, setBindings] = useState<BindingsValue>({
    default_profile_id: null,
    agent_profile_id: null,
  });
  const [phase, setPhase] = useState<
    "loading" | "ready" | "saving" | "locked" | "read-error"
  >("loading");
  const [error, setError] = useState<"read" | "save" | null>(null);
  const active = useRef<AbortController | null>(null);
  const generation = useRef(0);
  const busy = phase === "saving" || phase === "loading";
  const [saved, setSaved] = useState(false);
  const bindingDirty =
    !!snapshot &&
    (bindings.default_profile_id !== snapshot.default_profile_id ||
      bindings.agent_profile_id !== snapshot.agent_profile_id);
  const blocked =
    !snapshot ||
    phase !== "ready" ||
    snapshot.revision === Number.MAX_SAFE_INTEGER;
  function adopt(value: AISettingsSnapshot) {
    setSnapshot(value);
    setBindings({
      default_profile_id: value.default_profile_id,
      agent_profile_id: value.agent_profile_id,
    });
  }
  const read = useCallback(async (discard = false) => {
    active.current?.abort();
    const controller = new AbortController();
    active.current = controller;
    const token = ++generation.current;
    setPhase("loading");
    setSaved(false);
    try {
      const value = await aiSettingsAPI.read(controller.signal);
      if (token !== generation.current || controller.signal.aborted) return;
      adopt(value);
      setPhase("ready");
      setError(null);
      if (discard) {
        setDraft(null);
        setDeleting(null);
      }
    } catch {
      if (token === generation.current && !controller.signal.aborted) {
        setError("read");
        setPhase("read-error");
      }
    } finally {
      if (active.current === controller) active.current = null;
    }
  }, []);
  useEffect(() => {
    void read();
    return () => {
      ++generation.current;
      active.current?.abort();
      active.current = null;
    };
  }, [read]);
  async function save(input: AISettingsInput) {
    if (blocked || active.current) return;
    const controller = new AbortController();
    active.current = controller;
    const token = ++generation.current;
    setPhase("saving");
    setSaved(false);
    setError(null);
    try {
      const value = await aiSettingsAPI.save(input, controller.signal);
      if (token !== generation.current || controller.signal.aborted) return;
      adopt(value);
      setDraft(null);
      setDeleting(null);
      setSaved(true);
      setPhase("ready");
    } catch {
      if (token === generation.current && !controller.signal.aborted) {
        setError("save");
        setPhase("locked");
      }
    } finally {
      if (active.current === controller) active.current = null;
    }
  }
  function saveProfile(profile: AIModelProfile) {
    if (!snapshot) return;
    const exists = snapshot.profiles.some((p) => p.id === profile.id);
    if (!exists && snapshot.profiles.length >= 20) return;
    void save({
      revision: snapshot.revision,
      profiles: exists
        ? snapshot.profiles.map((p) => (p.id === profile.id ? profile : p))
        : [...snapshot.profiles, profile],
      default_profile_id: snapshot.default_profile_id,
      agent_profile_id: snapshot.agent_profile_id,
    });
  }
  const progress = busy && (
    <p role="status">
      {phase === "saving"
        ? t(
            "Saving draft settings… You may close the dialog; this does not cancel a submitted save.",
            "초안 설정 저장 중… 대화상자를 닫을 수 있지만 전송된 저장은 취소되지 않습니다.",
          )
        : t("Loading AI settings…", "AI 설정 불러오는 중…")}
    </p>
  );
  const recovery = error && (
    <Notice tone="danger">
      <div className="form-stack">
        <p>
          {error === "read"
            ? t(
                "Unable to read AI settings. No empty or sample data is substituted. Mutations are locked.",
                "AI 설정을 읽을 수 없습니다. 빈 목록이나 예시 데이터로 대체하지 않습니다. 변경이 잠겼습니다.",
              )
            : t(
                "The save was not acknowledged or conflicted. Its outcome may be unknown. Mutations are locked; your local form is preserved for inspection. Never retry automatically.",
                "저장이 확인되지 않았거나 충돌했습니다. 저장 결과를 알 수 없을 수 있습니다. 변경이 잠겼으며 검토용 로컬 양식은 유지됩니다. 자동 재시도하지 않습니다.",
              )}
        </p>
        {(draft || deleting || bindingDirty) && (
          <p>
            {t(
              "Reload reads the saved settings and discards your local edits. It does not replay or rebase them.",
              "다시 불러오면 저장된 설정을 읽고 로컬 편집을 취소합니다. 편집을 재전송하거나 자동 병합하지 않습니다.",
            )}
          </p>
        )}
        <Button disabled={busy} onClick={() => void read(true)}>
          {draft || deleting || bindingDirty
            ? t(
                "Reload saved settings (discard local edits)",
                "저장된 설정 다시 불러오기 (로컬 편집 취소)",
              )
            : t("Reload saved settings", "저장된 설정 다시 불러오기")}
        </Button>
      </div>
    </Notice>
  );
  const referenced = (id: string) =>
    snapshot?.default_profile_id === id || snapshot?.agent_profile_id === id;
  return (
    <div className="page-stack ai-settings-page">
      <PageHeader
        title={t("AI settings", "AI 설정")}
        eyebrow={t("AI & governance", "AI 및 거버넌스")}
        description={t(
          "Named model drafts for a review-only workspace. Protocol and vendor are separate choices.",
          "검토 전용 워크스페이스의 모델 초안입니다. 프로토콜은 공급자와 별개입니다.",
        )}
        actions={
          <Button
            variant="primary"
            disabled={
              blocked || bindingDirty || (snapshot?.profiles.length ?? 0) >= 20
            }
            onClick={() => {
              setDraft(newProfile());
              setSaved(false);
            }}
          >
            {t("Create profile", "프로필 만들기")}
          </Button>
        }
      />
      <Notice tone="warning">
        {t(
          "Draft configuration only · Not tested · Never executed. Saving does not activate a provider.",
          "초안 설정 전용 · 테스트 안 됨 · 실행한 적 없음. 저장해도 공급자가 활성화되지 않습니다.",
        )}
      </Notice>
      {saved && (
        <p role="status">
          {t(
            "Draft settings saved. No model was contacted.",
            "초안 설정이 저장되었습니다. 모델에 연결하지 않았습니다.",
          )}
        </p>
      )}
      {!draft && !deleting && recovery}
      {!draft && !deleting && progress}
      {snapshot?.revision === Number.MAX_SAFE_INTEGER && (
        <Notice tone="warning">
          {t(
            "The settings revision limit has been reached. Further mutations are unavailable.",
            "설정 리비전 한도에 도달했습니다. 더 이상 변경할 수 없습니다.",
          )}
        </Notice>
      )}
      {snapshot && (
        <>
          <Bindings
            snapshot={snapshot}
            value={bindings}
            disabled={blocked}
            dirty={bindingDirty}
            locale={locale}
            onChange={(value) => {
              setBindings(value);
              setSaved(false);
            }}
            onSave={() =>
              void save({
                revision: snapshot.revision,
                profiles: snapshot.profiles,
                ...bindings,
              })
            }
          />
          <p className="muted">
            {t(
              `${snapshot.profiles.length} / 20 profiles · 20-profile limit`,
              `${snapshot.profiles.length} / 20개 프로필 · 최대 20개`,
            )}
          </p>
          {snapshot.profiles.length === 0 ? (
            <Panel>
              <EmptyState
                title={t("No model profiles yet", "모델 프로필이 없습니다")}
                description={t(
                  "Create a draft with a model ID you supply. No provider is contacted.",
                  "모델 ID를 직접 입력하여 초안을 만드세요. 공급자에 연결하지 않습니다.",
                )}
              />
            </Panel>
          ) : (
            <div className="ais-cards">
              {snapshot.profiles.map((profile) => (
                <Panel
                  key={profile.id}
                  title={profile.name}
                  actions={
                    <div className="button-row">
                      <Button
                        disabled={blocked || bindingDirty}
                        aria-label={t("Edit ", "편집 ") + profile.name}
                        onClick={() => {
                          setDraft(profile);
                          setSaved(false);
                        }}
                      >
                        {t("Edit", "편집")}
                      </Button>
                      <Button
                        variant="danger"
                        disabled={
                          blocked || bindingDirty || referenced(profile.id)
                        }
                        aria-label={t("Delete ", "삭제 ") + profile.name}
                        onClick={() => setDeleting(profile)}
                      >
                        {t("Delete", "삭제")}
                      </Button>
                    </div>
                  }
                >
                  <div className="button-row">
                    <Badge>{profile.format}</Badge>
                    <Badge tone="warning">
                      {t("Draft / Not tested", "초안 / 테스트 안 됨")}
                    </Badge>
                    {snapshot.default_profile_id === profile.id && (
                      <Badge tone="info">
                        {t("Default draft", "기본 초안")}
                      </Badge>
                    )}
                    {snapshot.agent_profile_id === profile.id && (
                      <Badge tone="info">
                        {t("Review agent", "검토 에이전트")}
                      </Badge>
                    )}
                  </div>
                  <dl className="detail-list">
                    <dt>{t("Model ID", "모델 ID")}</dt>
                    <dd>
                      <code>{profile.model}</code>
                    </dd>
                    <dt>{t("Base URL", "기본 URL")}</dt>
                    <dd>
                      {profile.base_url ||
                        t(
                          "Protocol default (unspecified)",
                          "프로토콜 기본값 (미지정)",
                        )}
                    </dd>
                    <dt>{t("Credential", "자격 증명")}</dt>
                    <dd>
                      {profile.credential_env || t("No reference", "참조 없음")}
                    </dd>
                  </dl>
                  {referenced(profile.id) && (
                    <p className="muted">
                      {t(
                        "Clear or change its saved bindings before deleting this profile.",
                        "이 프로필을 삭제하기 전에 저장된 바인딩을 해제하거나 변경하세요.",
                      )}
                    </p>
                  )}
                </Panel>
              ))}
            </div>
          )}
        </>
      )}
      <Panel title={t("Connections are unavailable", "연결 기능 사용 불가")}>
        <div className="form-stack">
          <p className="muted">
            {t(
              "Connection tests and model discovery are disabled. This screen stores metadata only: no credential lookup, network connection or model execution.",
              "연결 테스트와 모델 검색은 비활성화되어 있습니다. 이 화면은 메타데이터만 저장하며 자격 증명 조회, 네트워크 연결, 모델 실행을 하지 않습니다.",
            )}
          </p>
          <div className="button-row">
            <Button disabled>{t("Test connection", "연결 테스트")}</Button>
            <Button disabled>{t("Discover models", "모델 검색")}</Button>
          </div>
        </div>
      </Panel>
      <Dialog
        open={draft !== null}
        title={
          snapshot?.profiles.some((p) => p.id === draft?.id)
            ? t("Edit model profile", "모델 프로필 편집")
            : t("Create model profile", "모델 프로필 만들기")
        }
        onClose={() => setDraft(null)}
      >
        {draft && (
          <div className="form-stack">
            {progress}
            {recovery}
            <ProfileEditor
              key={draft.id}
              initial={draft}
              profiles={snapshot?.profiles ?? []}
              locale={locale}
              disabled={blocked}
              onSave={saveProfile}
              onClose={() => setDraft(null)}
            />
          </div>
        )}
      </Dialog>
      <Dialog
        open={deleting !== null}
        title={t("Delete model profile", "모델 프로필 삭제")}
        onClose={() => setDeleting(null)}
      >
        {deleting && (
          <div className="form-stack">
            {progress}
            {recovery}
            <p>
              {t(
                "Delete this stored draft? This cannot be undone.",
                "저장된 초안을 삭제하시겠습니까? 되돌릴 수 없습니다.",
              )}
            </p>
            <strong>{deleting.name}</strong>
            <div className="button-row">
              <Button
                variant="danger"
                disabled={blocked || referenced(deleting.id)}
                onClick={() => {
                  if (snapshot && !referenced(deleting.id))
                    void save({
                      revision: snapshot.revision,
                      profiles: snapshot.profiles.filter(
                        (p) => p.id !== deleting.id,
                      ),
                      default_profile_id: snapshot.default_profile_id,
                      agent_profile_id: snapshot.agent_profile_id,
                    });
                }}
              >
                {t("Delete profile", "프로필 삭제")}
              </Button>
              <Button onClick={() => setDeleting(null)}>
                {t("Close", "닫기")}
              </Button>
            </div>
          </div>
        )}
      </Dialog>
    </div>
  );
}
