import { Archive, Fingerprint, FileClock, Layers3 } from "lucide-react";
import {
  Badge,
  Button,
  EmptyState,
  Notice,
  PageHeader,
  Panel,
} from "../../components/ui";
import type { PageProps } from "../../lib/contracts";
import { choose } from "../../lib/i18n";
import { LockedAction, RefreshWorkspace } from "./common";

export function EvidencePage({ locale, navigate, refresh }: PageProps) {
  const t = (en: string, ko: string) => choose(locale, en, ko);
  return (
    <div className="page-stack operations-page">
      <PageHeader
        eyebrow={t("Workspace / Artifacts", "워크스페이스 / 자료")}
        title={t("Evidence", "증거")}
        description={t(
          "A traceable record of what was measured, where it came from, and how it was retained.",
          "측정 내용, 출처, 보관 방식을 추적하는 기록입니다.",
        )}
        actions={
          <LockedAction
            label={t("Export evidence bundle", "증거 묶음 내보내기")}
            reason={t(
              "There are no retained run artifacts, and evidence export is not implemented.",
              "보관된 실행 자료가 없으며 증거 내보내기는 아직 구현되지 않았습니다.",
            )}
          />
        }
      />
      <RefreshWorkspace locale={locale} refresh={refresh} />
      <div className="operations-primary-grid">
        <Panel
          title={t("Artifact repository", "자료 저장소")}
          actions={<Badge>{t("Collection unavailable", "수집 불가")}</Badge>}
        >
          <EmptyState
            icon={<Archive size={32} />}
            title={t("No artifacts collected", "수집된 자료가 없습니다")}
            description={t(
              "No packet captures, measurement logs, or reports have been produced. There are no files to download or inspect.",
              "패킷 캡처, 측정 로그, 보고서가 생성되지 않았습니다. 다운로드하거나 검사할 파일이 없습니다.",
            )}
            action={
              <Button onClick={() => navigate("runs")}>
                {t("Open run workspace", "실행 워크스페이스 열기")}
              </Button>
            }
          />
        </Panel>
        <Panel title={t("Drafts ≠ evidence", "초안과 증거는 다릅니다")}>
          <Notice>
            {t(
              "Local drafts are not execution evidence.",
              "로컬 초안은 실행 증거가 아닙니다.",
            )}
          </Notice>
          <p className="muted">
            {t(
              "Configuration changes are recorded in the draft audit history. They do not prove a device was contacted, a policy passed, or an artifact was captured.",
              "구성 변경은 초안 감사 이력에 기록됩니다. 장치 접속, 정책 통과, 자료 수집을 입증하지는 않습니다.",
            )}
          </p>
          <Button variant="ghost" onClick={() => navigate("audit")}>
            {t("View draft audit history", "초안 감사 이력 보기")}
          </Button>
        </Panel>
      </div>
      <Panel
        title={t("Provenance & integrity requirements", "출처 및 무결성 요건")}
        description={t(
          "Design requirements for future collection, not claims about existing artifacts.",
          "향후 수집 기능의 설계 요건이며, 현재 자료에 대한 주장이 아닙니다.",
        )}
      >
        <ul className="operations-evidence-requirements">
          <li>
            <FileClock size={21} aria-hidden="true" />
            <div>
              <h3>{t("Origin & time", "출처 및 시각")}</h3>
              <p>
                {t(
                  "Link each artifact to its run, target, collector, and capture interval.",
                  "각 자료를 실행, 대상, 수집기, 수집 구간에 연결합니다.",
                )}
              </p>
            </div>
          </li>
          <li>
            <Fingerprint size={21} aria-hidden="true" />
            <div>
              <h3>{t("Integrity", "무결성")}</h3>
              <p>
                {t(
                  "Record content identity and verify bytes before relying on an artifact.",
                  "자료를 근거로 사용하기 전에 콘텐츠 식별값을 기록하고 바이트를 검증합니다.",
                )}
              </p>
            </div>
          </li>
          <li>
            <Layers3 size={21} aria-hidden="true" />
            <div>
              <h3>{t("Retention & access", "보관 및 접근")}</h3>
              <p>
                {t(
                  "Define authorized access and retention separately from local draft storage.",
                  "로컬 초안 저장과 별개로 접근 권한과 보관 정책을 정의합니다.",
                )}
              </p>
            </div>
          </li>
        </ul>
      </Panel>
    </div>
  );
}
