import { SPACE, TEXT_FORBIDDEN } from "./text-data";

export function inRanges(
  cp: number,
  ranges: ReadonlyArray<readonly [number, number]>,
): boolean {
  let lo = 0;
  let hi = ranges.length;
  while (lo < hi) {
    const mid = (lo + hi) >>> 1;
    const [start, end] = ranges[mid];
    if (cp < start) hi = mid;
    else if (cp > end) lo = mid + 1;
    else return true;
  }
  return false;
}
export const forbiddenText = (c: string): boolean =>
  inRanges(c.codePointAt(0)!, TEXT_FORBIDDEN);
export const pythonSpace = (c: string): boolean =>
  inRanges(c.codePointAt(0)!, SPACE);

export function literalText(value: unknown, max: number): value is string {
  if (typeof value !== "string" || !value) return false;
  const chars = Array.from(value);
  return (
    chars.length <= max &&
    !pythonSpace(chars[0]) &&
    !pythonSpace(chars[chars.length - 1]) &&
    !chars.some(forbiddenText)
  );
}
