import type { Locale } from "../../lib/contracts";
import type { Detail } from "./types";
import type { Detail as RunDetail } from "../runs/types";
import { parseDetail as parseRun } from "../runs/wire";
import { canonical, utf8Length } from "../scenarios/json";
import { bindRun, check, parseDetail } from "./codec";
import { label, warning, status } from "./labels";
export function boundedText(text: string, max: number) {
  check(utf8Length(text) <= max);
  return text;
}
export type Row = { key: string; title: string; value: string };
/** Only validated bounded values; no raw payloads, workspace paths or arbitrary HTML. */
export function rows(value: unknown, locale: Locale): Row[] {
  const result: Row[] = [];
  function visit(v: unknown, path: string[]) {
    if (v !== null && typeof v === "object" && !Array.isArray(v)) {
      for (const [k, x] of Object.entries(v)) visit(x, [...path, k]);
      return;
    }
    check(result.length < 256);
    const key = path.join("."),
      value = typeof v === "string" ? v : canonical(v);
    boundedText(value, 4096);
    let title = path.map((k) => label(k, locale)).join(" / ");
    if (key === "evidence.created_at")
      title = locale === "ko" ? "증거 등록 시각" : "Evidence registration time";
    result.push({ key, title, value });
  }
  visit(value, []);
  return result;
}
const escape = (s: string) =>
  s.replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ]!,
  );
export async function exportReport(
  input: Detail,
  source: RunDetail,
  locale: Locale,
) {
  check(locale === "en" || locale === "ko");
  const detail = await parseDetail(input),
    run = await parseRun(source);
  bindRun(detail, run);
  check(detail.report !== null);
  // The JSON preserves the exact canonical Detail and verified immutable Run, with no locale-dependent facts.
  const json = boundedText(
    canonical({ schema_version: 1, detail, offline_run: run }),
    65536,
  );
  const title =
    locale === "ko"
      ? "OFFLINE 캡처 단일 기준 보고서"
      : "OFFLINE capture criterion report";
  const data = rows(
    {
      evidence: detail.evidence,
      report: detail.report,
      declared_limits: run.result!.declared_limits,
    },
    locale,
  );
  const table = data
    .map(
      (r) =>
        `<tr><th scope="row">${escape(r.title)}<br><small>${escape(r.key)}</small></th><td>${escape(r.value)}</td></tr>`,
    )
    .join("");
  const html = boundedText(
    `<!doctype html><html lang="${locale}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'; img-src 'none'; object-src 'none'"><title>${escape(title)}</title><style>body{font:16px/1.6 system-ui,sans-serif;color:#e6edf4;background:#0b1119;margin:0;padding:24px}main{max-width:1000px;margin:auto}h1{font-size:26px}aside{border:1px solid #f1c775;padding:16px}table{border-collapse:collapse;width:100%;table-layout:fixed}th,td{border-bottom:1px solid #405363;padding:12px;text-align:left;vertical-align:top;overflow-wrap:anywhere;white-space:pre-wrap}th{width:48%}small{color:#9eafbf}@media(max-width:600px){body{padding:12px}th,td{display:block;width:auto}}</style></head><body><main><h1>${escape(title)}</h1><h2>${escape(status(detail.report.outcome, locale))}</h2><p>${escape(detail.report.provenance)} · ${escape(detail.report.coverage)} · CAPTURE_RECORDSET_ONLY</p><aside>${escape(warning(locale))}</aside><p>${locale === "ko" ? "생산자 시작 시각은 캡처 시각이나 완료 시각이 아닙니다." : "Producer start time is not capture time or completion time."}</p><table><caption>${locale === "ko" ? "검증된 원본 식별값, 정책 및 관측 사실" : "Validated original identities, policy and observed facts"}</caption><tbody>${table}</tbody></table></main></body></html>`,
    131072,
  );
  return { json, html };
}
export function download(
  value: string | Uint8Array,
  type: string,
  filename: string,
): () => void {
  const blob = new Blob(
    [typeof value === "string" ? value : new Uint8Array(value)],
    { type },
  );
  const url = URL.createObjectURL(blob);
  let retired = false;
  const retire = () => {
    if (!retired) {
      retired = true;
      clearTimeout(timer);
      URL.revokeObjectURL(url);
    }
  };
  const timer = setTimeout(retire, 1000);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  try {
    document.body.append(a);
    a.click();
  } catch (error) {
    retire();
    throw error;
  } finally {
    a.remove();
  }
  return retire;
}
