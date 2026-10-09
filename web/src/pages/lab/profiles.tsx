import { useState } from "react";
import { ArrowRight, FileSliders, LockKeyhole } from "lucide-react";
import {
  Badge,
  Button,
  Dialog,
  EmptyState,
  Notice,
  PageHeader,
  Panel,
} from "../../components/ui";
import type { PageProps } from "../../lib/contracts";
import { choose, text } from "../../lib/i18n";

export function ProfilesPage({ data, locale, navigate }: PageProps) {
  const c = (en: string, ko: string) => choose(locale, en, ko);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const selected = data.profiles.find((profile) => profile.id === selectedId);
  return (
    <div className="page-stack lab-page">
      <PageHeader
        eyebrow={c("Lab configuration", "실험실 구성")}
        title={c("Traffic profiles", "트래픽 프로파일")}
        description={c(
          "Inspect the built-in planning templates supplied by the API. A template describes intent, not a running or approved test.",
          "API에서 제공하는 기본 계획 템플릿을 살펴보세요. 템플릿은 의도를 설명하며 실행 중이거나 승인된 시험이 아닙니다.",
        )}
      />
      <Notice>
        {c(
          "Template metadata only. Engine installation, hardware availability, and operational approval have not been verified.",
          "템플릿 메타데이터만 표시합니다. 엔진 설치, 하드웨어 가용성, 운영 승인은 검증되지 않았습니다.",
        )}
      </Notice>
      <Panel
        title={c("Built-in template catalog", "기본 템플릿 목록")}
        actions={
          <Badge>
            {data.profiles.length} {c("templates", "개 템플릿")}
          </Badge>
        }
      >
        {data.profiles.length === 0 ? (
          <EmptyState
            icon={<FileSliders size={28} />}
            title={c(
              "No profile templates available",
              "사용 가능한 프로파일 템플릿이 없습니다",
            )}
            description={c(
              "The current workspace snapshot contains no profiles. Check the local API from Settings; no example profiles are substituted.",
              "현재 워크스페이스에 프로파일이 없습니다. 설정에서 로컬 API를 확인하세요. 예시 프로파일로 대체하지 않습니다.",
            )}
            action={
              <Button onClick={() => navigate("settings")}>
                {c("Open settings", "설정 열기")}
              </Button>
            }
          />
        ) : (
          <div className="grid-three">
            {data.profiles.map((profile) => (
              <article className="item-card lab-profile-card" key={profile.id}>
                <div className="chips">
                  <Badge tone="info">{profile.engine}</Badge>
                  <Badge>{profile.layer}</Badge>
                </div>
                <h3>{text(profile.name, locale)}</h3>
                <p className="muted">{text(profile.description, locale)}</p>
                <Badge tone="warning">
                  {c("Template · not executed", "템플릿 · 미실행")}
                </Badge>
                <Button
                  aria-label={
                    c("View details: ", "상세 보기: ") +
                    text(profile.name, locale)
                  }
                  onClick={() => setSelectedId(profile.id)}
                >
                  {c("View details", "상세 보기")}
                  <ArrowRight size={16} aria-hidden="true" />
                </Button>
              </article>
            ))}
          </div>
        )}
      </Panel>
      <Dialog
        open={Boolean(selected)}
        title={
          selected
            ? text(selected.name, locale)
            : c("Profile details", "프로파일 상세")
        }
        onClose={() => setSelectedId(null)}
      >
        {selected && (
          <div className="form-stack">
            <Badge tone="warning">
              {c("Template · not executed", "템플릿 · 미실행")}
            </Badge>
            <p>{text(selected.description, locale)}</p>
            <dl className="detail-list">
              <div>
                <dt>{c("Template ID", "템플릿 ID")}</dt>
                <dd className="mono">{selected.id}</dd>
              </div>
              <div>
                <dt>{c("Engine", "엔진")}</dt>
                <dd className="mono">{selected.engine}</dd>
              </div>
              <div>
                <dt>{c("Network layer", "네트워크 계층")}</dt>
                <dd>{selected.layer}</dd>
              </div>
            </dl>
            <h3>{c("Before a future execution", "향후 실행 전 준비 사항")}</h3>
            <ul className="lab-checklist">
              <li>
                {c(
                  "Choose an owned target and document the test objective and boundaries.",
                  "소유한 시험 대상을 선택하고 시험 목적과 범위를 기록하세요.",
                )}
              </li>
              <li>
                {c(
                  "Verify the engine, instrument capabilities, and evidence collection path.",
                  "엔진, 계측기 기능, 증거 수집 경로를 검증하세요.",
                )}
              </li>
              <li>
                {c(
                  "Obtain explicit approval through the future Safety Gate before any traffic or capture.",
                  "트래픽 전송 또는 캡처 전에 향후 안전 게이트를 통해 명시적 승인을 받으세요.",
                )}
              </li>
            </ul>
            <Notice tone="warning">
              <span id="profile-execution-reason">
                {c(
                  "Templates do not authorize execution. Live execution is unavailable.",
                  "템플릿은 실행 권한을 부여하지 않습니다. 실제 실행은 사용할 수 없습니다.",
                )}
              </span>
            </Notice>
            <div className="button-row">
              <Button disabled aria-describedby="profile-execution-reason">
                <LockKeyhole size={16} aria-hidden="true" />
                {c("Execute profile", "프로파일 실행")}
              </Button>
              <Button
                variant="primary"
                onClick={() => {
                  setSelectedId(null);
                  navigate("campaigns");
                }}
              >
                {c("Open campaign drafts", "캠페인 초안 열기")}
              </Button>
            </div>
          </div>
        )}
      </Dialog>
    </div>
  );
}
