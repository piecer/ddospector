export function hasControl(value: string): boolean {
  return [...value].some(
    (char) => char.charCodeAt(0) < 32 || char.charCodeAt(0) === 127,
  );
}

export function validName(value: string): boolean {
  return value.trim().length > 0 && value.length <= 120 && !hasControl(value);
}

export function validEndpoint(
  value: string,
  transport: "streamable_http" | "stdio",
): boolean {
  if (transport === "stdio") return /^[a-z][a-z0-9-]{0,63}$/.test(value);
  if (
    !value ||
    value.length > 512 ||
    hasControl(value) ||
    /[\s\\#?]/.test(value) ||
    !/^https?:\/\//i.test(value)
  )
    return false;
  // Reject even empty userinfo (https://@host), which URL parsing normalizes away.
  const authority = /^https?:\/\/([^/?#]+)/i.exec(value)?.[1];
  if (!authority || authority.includes("@")) return false;
  try {
    const url = new URL(value);
    return (
      Boolean(url.hostname) &&
      (url.protocol === "http:" || url.protocol === "https:") &&
      !url.username &&
      !url.password &&
      !url.hash
    );
  } catch {
    return false;
  }
}

export function validAddress(value: string): boolean {
  if (!value || value.length > 255 || hasControl(value) || /\s/.test(value))
    return false;
  if (value.includes(":")) {
    if (!/^[\da-f:.]+$/i.test(value)) return false;
    try {
      return new URL(`http://[${value}]/`).hostname.startsWith("[");
    } catch {
      return false;
    }
  }
  if (/^[\d.]+$/.test(value)) {
    const parts = value.split(".");
    return (
      parts.length === 4 &&
      parts.every(
        (part) => /^(0|[1-9]\d{0,2})$/.test(part) && Number(part) <= 255,
      )
    );
  }
  const hostname = value.endsWith(".") ? value.slice(0, -1) : value;
  return (
    hostname.length <= 253 &&
    hostname
      .split(".")
      .every((label) => /^[a-z\d](?:[a-z\d-]{0,61}[a-z\d])?$/i.test(label))
  );
}
