import type { Locale, LocalizedText } from "./contracts";
export function text(value: LocalizedText, locale: Locale): string {
  return value[locale];
}
export function choose(locale: Locale, en: string, ko: string): string {
  return locale === "ko" ? ko : en;
}
export function formatDate(value: string, locale: Locale): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "—"
    : new Intl.DateTimeFormat(locale === "ko" ? "ko-KR" : "en-US", {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      }).format(date);
}
