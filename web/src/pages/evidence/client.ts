import { canonical } from "../scenarios/json";
import { exact } from "../scenarios/validation";
import { uuid } from "../runs/wire";
import { rawJSON } from "../runs/raw";
import { snapshot } from "../runs/object";
import { check, decodeDetail, decodeList, validName, sides } from "./codec";
import { sampleCatalog, manifestSHA } from "./catalog";
import { errors, EvidenceError } from "./errors";
import type { Descriptor, Side, Summary, Upload } from "./types";
export const MAX_BYTES = 65536,
  TIMEOUT = 10000;
/** Deadline includes body acquisition and consumer validation, with late publication refusal. */
export async function bounded<T = { bytes: Uint8Array; status: number }>(
  path: string,
  init: RequestInit = {},
  max = MAX_BYTES,
  consume?: (bytes: Uint8Array, status: number) => T | Promise<T>,
): Promise<T> {
  const controller = new AbortController(),
    start = performance.now();
  init.signal?.throwIfAborted();
  const abort = () => {
    if (!controller.signal.aborted) controller.abort();
  };
  init.signal?.addEventListener("abort", abort, { once: true });
  let reject!: (reason: unknown) => void;
  const aborted = new Promise<never>((_, r) => {
    reject = r;
  });
  let retireResponse = () => {};
  const onAbort = () => {
    retireResponse();
    reject(new EvidenceError("EVIDENCE_CLIENT_TIMEOUT"));
  };
  controller.signal.addEventListener("abort", onAbort, { once: true });
  const timer = setTimeout(abort, TIMEOUT);
  const live = () => {
    if (performance.now() - start >= TIMEOUT) abort();
    controller.signal.throwIfAborted();
  };
  async function perform(): Promise<T> {
    const response = await fetch(path, {
      ...init,
      credentials: "same-origin",
      redirect: "error",
      cache: "no-store",
      signal: controller.signal,
    });
    let reader: ReadableStreamDefaultReader<Uint8Array> | undefined;
    let retired = false;
    // Ownership starts at fetch resolution, before any header/body admission.
    // Cancellation may itself reject or never settle; neither delays retirement
    // nor replaces the operation's primary error.
    retireResponse = () => {
      if (retired) return;
      retired = true;
      try {
        void (reader ? reader.cancel() : response.body?.cancel())?.catch(
          () => undefined,
        );
      } catch {
        /* Preserve the primary failure. */
      }
      try {
        reader?.releaseLock();
      } catch {
        /* Already released/unavailable. */
      }
    };
    let complete = false;
    try {
      live();
      check(!response.redirected && !response.headers.get("Content-Encoding"));
      reader = response.body?.getReader();
      check(reader);
      const length = response.headers.get("Content-Length");
      check(
        length === null ||
          (/^[0-9]{1,10}$/.test(length) && Number(length) <= max),
      );
      const chunks: Uint8Array[] = [];
      let size = 0,
        frames = 0;
      while (true) {
        const chunk = await reader.read();
        live();
        if (chunk.done) break;
        check(++frames <= 4096);
        size += chunk.value.byteLength;
        check(size <= max);
        if (chunk.value.byteLength) chunks.push(chunk.value);
      }
      const bytes = new Uint8Array(size);
      let offset = 0;
      for (const c of chunks) {
        bytes.set(c, offset);
        offset += c.byteLength;
      }
      const result = consume
        ? await consume(bytes, response.status)
        : ({ bytes, status: response.status } as T);
      live();
      complete = true;
      return result;
    } finally {
      if (!complete) {
        // Cleanup abort is not a timeout: retain validation/HTTP error identity.
        controller.signal.removeEventListener("abort", onAbort);
        retireResponse();
        abort();
      } else if (!retired) {
        retired = true;
        reader?.releaseLock();
      }
    }
  }
  try {
    return await Promise.race([perform(), aborted]);
  } finally {
    clearTimeout(timer);
    init.signal?.removeEventListener("abort", abort);
    controller.signal.removeEventListener("abort", onAbort);
  }
}
function httpError(bytes: Uint8Array, status: number) {
  const v = rawJSON(bytes, 1024);
  check(
    exact(v, ["code", "message"]) &&
      typeof v.code === "string" &&
      Object.hasOwn(errors, v.code),
  );
  const [expected, message] = errors[v.code];
  check(status === expected && v.message === message);
  throw new EvidenceError(v.code);
}
const prefix = "/api/v1/evidence";
async function detail(
  path: string,
  init: RequestInit = {},
  id?: string,
  byRequest = false,
) {
  return bounded(prefix + path, init, MAX_BYTES, async (bytes, status) => {
    if (status >= 300) httpError(bytes, status);
    check(
      init.method === "POST"
        ? status === 200 || status === 201
        : status === 200,
    );
    const d = await decodeDetail(bytes);
    if (id) check((byRequest ? d.evidence.request_id : d.evidence.id) === id);
    return d;
  });
}
let posting = false;
export const evidenceAPI = {
  list(signal?: AbortSignal) {
    return bounded(prefix, { signal }, MAX_BYTES, (b, s) => {
      if (s >= 300) httpError(b, s);
      check(s === 200);
      return decodeList(b);
    });
  },
  get(id: string, signal?: AbortSignal) {
    check(uuid(id));
    return detail("/" + id, { signal }, id);
  },
  byRequest(id: string, signal?: AbortSignal) {
    check(uuid(id));
    return detail("/by-request/" + id, { signal }, id, true);
  },
  async post(input: Upload, signal?: AbortSignal) {
    check(!posting);
    const captured = snapshot(input, 262144);
    check(
      exact(captured, ["request_id", "run_id", "ingress", "egress"]) &&
        uuid(captured.request_id) &&
        uuid(captured.run_id),
    );
    for (const side of sides) {
      const v = captured[side];
      check(
        exact(v, ["name", "base64"]) &&
          validName(v.name) &&
          typeof v.base64 === "string" &&
          v.base64.length >= 4 &&
          v.base64.length <= 87384 &&
          v.base64.length % 4 === 0,
      );
      check(
        /^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(
          v.base64,
        ),
      );
      const raw = atob(v.base64);
      check(
        raw.length >= 1 && raw.length <= MAX_BYTES && btoa(raw) === v.base64,
      );
    }
    const body = canonical(captured);
    check(new TextEncoder().encode(body).byteLength <= 262144);
    posting = true;
    try {
      return await detail(
        "",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body,
          signal,
        },
        captured.request_id,
        true,
      );
    } finally {
      posting = false;
    }
  },
  raw(s: Summary, side: Side, signal?: AbortSignal) {
    check(uuid(s.id) && sides.includes(side));
    return bounded(
      `${prefix}/${s.id}/raw/${side}`,
      { signal },
      MAX_BYTES,
      async (b, status) => {
        if (status >= 300) httpError(b, status);
        check(status === 200);
        await verifyBytes(b, s[side]);
        return b;
      },
    );
  },
};
export async function hashBytes(b: Uint8Array): Promise<string> {
  const hash = await crypto.subtle.digest("SHA-256", new Uint8Array(b));
  return Array.from(new Uint8Array(hash), (x) =>
    x.toString(16).padStart(2, "0"),
  ).join("");
}
export async function verifyBytes(
  b: Uint8Array,
  d: Pick<Descriptor, "size_bytes" | "sha256">,
) {
  check(
    b.byteLength === d.size_bytes &&
      b.byteLength >= 1 &&
      b.byteLength <= MAX_BYTES &&
      (await hashBytes(b)) === d.sha256,
  );
}
export function admitFile(f: File) {
  check(
    validName(f.name) &&
      Number.isInteger(f.size) &&
      f.size >= 1 &&
      f.size <= MAX_BYTES,
  );
}
export async function prepareFiles(
  ingress: File,
  egress: File,
  signal?: AbortSignal,
) {
  // Both descriptors must pass before either File.arrayBuffer(), hash or base64.
  admitFile(ingress);
  admitFile(egress);
  signal?.throwIfAborted();
  async function one(f: File) {
    const bytes = new Uint8Array(await f.arrayBuffer());
    signal?.throwIfAborted();
    check(bytes.length === f.size);
    const sha256 = await hashBytes(bytes);
    signal?.throwIfAborted();
    let text = "";
    for (const b of bytes) text += String.fromCharCode(b);
    return {
      descriptor: { name: f.name, size_bytes: bytes.length, sha256 },
      input: { name: f.name, base64: btoa(text) },
    };
  }
  return { ingress: await one(ingress), egress: await one(egress) };
}
export async function loadSample(
  id: (typeof sampleCatalog)[number]["sample_id"],
  signal?: AbortSignal,
) {
  const sample = sampleCatalog.find((x) => x.sample_id === id);
  check(sample);
  const manifest = await bounded(
    "/evidence-samples-v1/manifest.json",
    { signal },
    8192,
  );
  check(
    manifest.status === 200 &&
      (await hashBytes(manifest.bytes)) === manifestSHA,
  );
  signal?.throwIfAborted();
  async function one(side: Side) {
    const d = sample![side];
    return bounded(
      "/evidence-samples-v1/" + d.filename,
      { signal },
      MAX_BYTES,
      async (bytes, status) => {
        check(status === 200);
        await verifyBytes(bytes, d);
        return new File([new Uint8Array(bytes)], d.filename, {
          type: "application/octet-stream",
        });
      },
    );
  }
  return { ingress: await one("ingress"), egress: await one("egress") };
}
