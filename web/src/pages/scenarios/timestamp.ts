/** Python 3.12 datetime.fromisoformat's aware date/time forms, without URL/Date.parse normalization. */
export function timestamp(value: unknown): boolean {
  if (typeof value !== "string") return false;
  const s = Array.from(value),
    length = s.length;
  if (
    length < 20 ||
    length > 40 ||
    s.some((c) => {
      const cp = c.codePointAt(0)!;
      return cp >= 0xd800 && cp <= 0xdfff;
    })
  )
    return false;
  const digit = (c: string | undefined) =>
    c !== undefined && c >= "0" && c <= "9";
  let split: number;
  if (s[4] === "-") {
    if (s[5] === "W") split = s[8] === "-" && !digit(s[10]) ? 10 : 8;
    else split = 10;
  } else if (s[4] === "W") {
    let i = 7;
    while (digit(s[i])) i++;
    split = i < 9 ? i : i % 2 === 0 ? 7 : 8;
  } else split = 8;
  const date = s.slice(0, split).join("");
  const calendar = /^(\d{4})(-?)(\d{2})\2(\d{2})$/.exec(date);
  const week = /^(\d{4})(-?)W(\d{2})(?:\2([1-7]))?$/.exec(date);
  if (calendar) {
    const year = Number(calendar[1]),
      month = Number(calendar[3]),
      day = Number(calendar[4]);
    const days = [
      31,
      year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0) ? 29 : 28,
      31,
      30,
      31,
      30,
      31,
      31,
      30,
      31,
      30,
      31,
    ];
    if (year < 1 || month < 1 || month > 12 || day < 1 || day > days[month - 1])
      return false;
  } else if (week) {
    const year = Number(week[1]),
      number = Number(week[3]),
      day = Number(week[4] ?? 1);
    if (year < 1 || number < 1 || number > 53) return false;
    const jan4 = new Date(0);
    jan4.setUTCFullYear(year, 0, 4);
    const monday = jan4.getTime() - ((jan4.getUTCDay() + 6) % 7) * 86400000;
    const dec28 = new Date(0);
    dec28.setUTCFullYear(year, 11, 28);
    if (number > Math.floor((dec28.getTime() - monday) / 604800000) + 1)
      return false;
    const resultYear = new Date(
      monday + ((number - 1) * 7 + day - 1) * 86400000,
    ).getUTCFullYear();
    if (resultYear < 1 || resultYear > 9999) return false;
  } else return false;
  const rest = s.slice(split + 1).join("");
  const zoneStart = rest.search(/[+Z-]/);
  if (zoneStart < 0) return false;
  const clock = components(rest.slice(0, zoneStart));
  if (!clock || clock[0] > 23 || clock[1] > 59 || clock[2] >= 60) return false;
  const zone = rest.slice(zoneStart);
  if (zone === "Z") return true;
  if (zone[0] !== "+" && zone[0] !== "-") return false;
  const offset = components(zone.slice(1));
  return (
    offset !== null && offset[0] * 3600 + offset[1] * 60 + offset[2] < 86400
  );
}
function components(s: string): [number, number, number] | null {
  const m = /^(\d{2})(?:(:?)(\d{2})(?:\2(\d{2}))?)?(?:[.,](\d+))?$/.exec(s);
  if (!m) return null;
  return [
    Number(m[1]),
    Number(m[3] ?? 0),
    Number(m[4] ?? 0) + Number("0." + (m[5] ?? "0").slice(0, 6)),
  ];
}
