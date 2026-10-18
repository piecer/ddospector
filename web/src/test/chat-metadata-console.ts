export type ConsoleFact = { text: string; url: string };
export type MetadataResponse = {
  order: number;
  url: string;
  method: string;
  status: number;
  code?: string;
};

export function unexpectedConsole(
  errors: readonly ConsoleFact[],
  responses: readonly MetadataResponse[],
  origin: string,
): ConsoleFact[] {
  const urls = new Set(
    ["runtime", "sessions", "tools/runtime", "tools/fence"].map(
      (path) => `${origin}/api/v1/chat/${path}`,
    ),
  );
  const recovered = responses.filter(
    (busy) =>
      urls.has(busy.url) &&
      busy.method === "GET" &&
      busy.status === 429 &&
      busy.code === "CHAT_BUSY" &&
      responses.some(
        (next) =>
          next.order > busy.order &&
          next.url === busy.url &&
          next.method === "GET" &&
          next.status === 200,
      ),
  );
  return errors.filter((error) => {
    if (
      error.text !==
      "Failed to load resource: the server responded with a status of 429 (Too Many Requests)"
    )
      return true;
    const index = recovered.findIndex((busy) => busy.url === error.url);
    if (index < 0) return true;
    recovered.splice(index, 1);
    return false;
  });
}
