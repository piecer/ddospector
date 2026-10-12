export const errors: Record<string, readonly [number, string]> = {
  RUN_BODY_TOO_LARGE: [413, "Offline run request exceeds the 1024-byte limit."],
  RUN_DB_NOT_CONFIGURED: [503, "Offline run storage is not configured."],
  RUN_DB_NOT_READY: [
    503,
    "Offline run storage requires the supported schema and durability settings.",
  ],
  RUN_DB_UNAVAILABLE: [503, "Offline run storage is unavailable."],
  RUN_BUSY: [429, "Offline run storage admission is busy."],
  RUN_SOURCE_NOT_FOUND: [404, "No such scenario version."],
  RUN_SOURCE_CONFLICT: [409, "The selected scenario digest does not match."],
  RUN_STATE_CORRUPT: [
    503,
    "Retained offline run data is invalid; no repair was performed.",
  ],
  RUN_RETENTION_FULL: [
    409,
    "Offline run retention is full; existing records were preserved.",
  ],
  RUN_QUEUE_FULL: [429, "The offline run queue is full."],
  RUN_NOT_FOUND: [404, "No such offline run or request."],
  RUN_IDEMPOTENCY_CONFLICT: [
    409,
    "This request ID is bound to different input.",
  ],
  RUN_COMMIT_UNCERTAIN: [
    503,
    "The operation may have committed. Read by request or run ID before retrying.",
  ],
  SCENARIO_STATE_CORRUPT: [
    503,
    "Scenario state is invalid; restore it before editing.",
  ],
  SCENARIO_STATE_UNAVAILABLE: [
    503,
    "Scenario storage is unavailable or write-quarantined. History reads do not unlock saves; follow the offline recovery guide.",
  ],
  INTERNAL_ERROR: [500, "The draft service could not complete the request."],
  NOT_FOUND: [404, "No such API route."],
  METHOD_NOT_ALLOWED: [405, "This method is not supported."],
  REQUEST_TIMEOUT: [
    408,
    "Request body was not received within the time limit.",
  ],
  ORIGIN_NOT_ALLOWED: [
    403,
    "Origin is not allowed for this development workspace.",
  ],
  HOST_NOT_ALLOWED: [403, "Only loopback development hosts are allowed."],
  JSON_REQUIRED: [
    415,
    "Mutations require application/json with UTF-8 encoding.",
  ],
  UNSUPPORTED_ENCODING: [415, "Encoded request bodies are unsupported."],
  INVALID_FRAMING: [400, "Invalid request framing."],
  BODY_TOO_LARGE: [413, "Request body exceeds the 256 KiB limit."],
  VALIDATION_ERROR: [422, "Invalid request data."],
  LIVE_NOT_AVAILABLE: [
    409,
    "LIVE execution is unavailable in this draft workspace.",
  ],
};
export class RunError extends Error {
  constructor(public readonly code: string) {
    super("Offline run request failed.");
  }
}
