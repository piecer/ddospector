import { CASE_FOLD } from "./casefold-data";

// Full Unicode 15.0.0 casefold, matching project Python 3.12. Characters absent
// from the generated map are identities, NOT the browser's newer lowercase.
// Compare only: never normalize or replace the operator's stored strings.
export function casefold(value: string): string {
  return Array.from(value, (c) => CASE_FOLD[c.codePointAt(0)!] ?? c).join("");
}
