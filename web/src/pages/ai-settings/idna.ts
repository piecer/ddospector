// Syntactic CPython 3.12 IDNA2003 encoding for draft metadata only. This is NOT
// browser navigation, DNS, IDNA2008/UTS46, or a transport security policy.
import {
  COMBINING,
  COMPOSE,
  IDNA_PROHIBITED,
  LCAT,
  NAMEPREP_DECOMPOSE,
  RANDAL,
} from "./idna-data";
import { inRanges } from "./unicode-text";

const chars = (value: string) => Array.from(value, (c) => c.codePointAt(0)!);
const text = (points: number[]) =>
  points.map((cp) => String.fromCodePoint(cp)).join("");
const combining = (cp: number) => COMBINING[cp] ?? 0;

function decompose(cp: number): number[] {
  // Unicode Hangul decomposition is algorithmic; all other transformations are
  // generated directly from CPython's B1/B2 + ucd_3_2_0.NFKD, including corrections.
  const syllable = cp - 0xac00;
  if (syllable >= 0 && syllable < 11172) {
    const result = [
      0x1100 + Math.floor(syllable / 588),
      0x1161 + Math.floor((syllable % 588) / 28),
    ];
    if (syllable % 28) result.push(0x11a7 + (syllable % 28));
    return result;
  }
  return chars(NAMEPREP_DECOMPOSE[cp] ?? String.fromCodePoint(cp));
}
function composePair(a: number, b: number): number | undefined {
  if (a >= 0x1100 && a < 0x1113 && b >= 0x1161 && b < 0x1176)
    return 0xac00 + ((a - 0x1100) * 21 + b - 0x1161) * 28;
  if (
    a >= 0xac00 &&
    a <= 0xd7a3 &&
    (a - 0xac00) % 28 === 0 &&
    b > 0x11a7 &&
    b < 0x11c3
  )
    return a + b - 0x11a7;
  return COMPOSE[`${a},${b}`]?.codePointAt(0);
}
function nameprep(value: string): string | null {
  const ordered: number[] = [];
  for (const cp of chars(value).flatMap(decompose)) {
    let index = ordered.length;
    const cc = combining(cp);
    while (cc && index > 0 && combining(ordered[index - 1]) > cc) index--;
    ordered.splice(index, 0, cp);
  }
  const normalized: number[] = [];
  let starter = -1;
  let lastClass = 0;
  for (const cp of ordered) {
    const cc = combining(cp);
    const composite =
      starter < 0 ? undefined : composePair(normalized[starter], cp);
    if (composite !== undefined && (lastClass === 0 || lastClass < cc)) {
      normalized[starter] = composite;
    } else {
      if (cc === 0) starter = normalized.length;
      normalized.push(cp);
      lastClass = cc;
    }
  }
  if (normalized.some((cp) => inRanges(cp, IDNA_PROHIBITED))) return null;
  if (
    normalized.some((cp) => inRanges(cp, RANDAL)) &&
    (normalized.some((cp) => inRanges(cp, LCAT)) ||
      !inRanges(normalized[0], RANDAL) ||
      !inRanges(normalized[normalized.length - 1], RANDAL))
  )
    return null;
  return text(normalized);
}

// RFC 3492 encoding only; the input is bounded by the outer 512-code-point URL
// guard and Nameprep. No decoding or network-facing hostname is returned to UI.
function punycode(value: string): string {
  const points = chars(value);
  const basic = points.filter((cp) => cp < 128);
  let output = text(basic) + (basic.length ? "-" : "");
  let handled = basic.length;
  let n = 128;
  let delta = 0;
  let bias = 72;
  const digit = (d: number) => String.fromCharCode(d < 26 ? 97 + d : 22 + d);
  while (handled < points.length) {
    const next = Math.min(...points.filter((cp) => cp >= n));
    delta += (next - n) * (handled + 1);
    n = next;
    for (const cp of points) {
      if (cp < n) delta++;
      if (cp !== n) continue;
      let q = delta;
      for (let k = 36; ; k += 36) {
        const threshold = Math.max(1, Math.min(26, k - bias));
        if (q < threshold) break;
        output += digit(threshold + ((q - threshold) % (36 - threshold)));
        q = Math.floor((q - threshold) / (36 - threshold));
      }
      output += digit(q);
      let adapted = Math.floor(delta / (handled === basic.length ? 700 : 2));
      adapted += Math.floor(adapted / (handled + 1));
      let k = 0;
      while (adapted > 455) {
        adapted = Math.floor(adapted / 35);
        k += 36;
      }
      bias = k + Math.floor((36 * adapted) / (adapted + 38));
      delta = 0;
      handled++;
    }
    delta++;
    n++;
  }
  return output;
}
function asciiLabel(label: string): string | null {
  if (chars(label).some((cp) => cp >= 128)) {
    const prepared = nameprep(label);
    if (prepared === null) return null;
    label = prepared;
    if (chars(label).some((cp) => cp >= 128)) {
      if (label.startsWith("xn--")) return null;
      label = "xn--" + punycode(label);
    }
  }
  return label.length > 0 && label.length < 64 ? label : null;
}
export function idnaASCII(host: string): string | null {
  const labels = host.split(/[.\u3002\uff0e\uff61]/u);
  const trailing = labels.length > 1 && labels[labels.length - 1] === "";
  if (trailing) labels.pop();
  const ascii = labels.map(asciiLabel);
  if (ascii.some((label) => label === null)) return null;
  return ascii.join(".") + (trailing ? "." : "");
}
