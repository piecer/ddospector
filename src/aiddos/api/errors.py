"""Fixed public failures; no exception, filesystem or request values are reflected."""

from starlette.responses import JSONResponse

ERRORS = {
    "EVIDENCE_NOT_READY": (503, "Evidence storage requires a fresh create --evidence workspace."),
    "EVIDENCE_NOT_FOUND": (404, "No such evidence bundle or request."),
    "EVIDENCE_RUN_NOT_READY": (409, "Evidence requires a valid succeeded OFFLINE run."),
    "EVIDENCE_IDEMPOTENCY_CONFLICT": (409, "This request ID is bound to different evidence."),
    "EVIDENCE_RETENTION_FULL": (
        409, "Evidence retention is full; existing records were preserved."
    ),
    "EVIDENCE_STATE_CORRUPT": (503, "Retained evidence is invalid; no repair was performed."),
    "EVIDENCE_CAPTURE_TOO_LARGE": (413, "Evidence capture exceeds the 65536-byte limit."),
    "EVIDENCE_BUSY": (429, "Another evidence upload is in progress."),
    "RUN_BODY_TOO_LARGE": (413, "Offline run request exceeds the 1024-byte limit."),
    "RUN_DB_NOT_CONFIGURED": (503, "Offline run storage is not configured."),
    "RUN_DB_NOT_READY": (
        503,
        "Offline run storage requires the supported schema and durability settings.",
    ),
    "RUN_DB_UNAVAILABLE": (503, "Offline run storage is unavailable."),
    "RUN_BUSY": (429, "Offline run storage admission is busy."),
    "RUN_SOURCE_NOT_FOUND": (404, "No such scenario version."),
    "RUN_SOURCE_CONFLICT": (409, "The selected scenario digest does not match."),
    "RUN_STATE_CORRUPT": (503, "Retained offline run data is invalid; no repair was performed."),
    "RUN_RETENTION_FULL": (409, "Offline run retention is full; existing records were preserved."),
    "RUN_QUEUE_FULL": (429, "The offline run queue is full."),
    "RUN_NOT_FOUND": (404, "No such offline run or request."),
    "RUN_IDEMPOTENCY_CONFLICT": (409, "This request ID is bound to different input."),
    "RUN_COMMIT_UNCERTAIN": (
        503,
        "The operation may have committed. Read by request or run ID before retrying.",
    ),
    "SCENARIO_CONFLICT": (409, "Scenario history changed; reload before saving again."),
    "SCENARIO_NOT_FOUND": (404, "No such scenario definition."),
    "SCENARIO_LIMIT_REACHED": (409, "Scenario identity or version limit reached."),
    "SCENARIO_STATE_CORRUPT": (503, "Scenario state is invalid; restore it before editing."),
    "SCENARIO_STATE_UNAVAILABLE": (
        503,
        "Scenario storage is unavailable or write-quarantined. History reads do not unlock saves; "
        "follow the offline recovery guide.",
    ),
    "SCENARIO_COMMIT_UNCERTAIN": (
        503,
        "Scenario may have been saved. Read its history; unresolved storage failure requires "
        "offline recovery. Do not resubmit automatically.",
    ),
    "AI_CONNECTION_NOT_AVAILABLE": (
        409,
        "AI connection tests and model discovery are unavailable in this draft workspace.",
    ),
    "AI_SETTINGS_CONFLICT": (409, "AI settings changed; reload before saving again."),
    "AUDIT_LIMIT_REACHED": (409, "The local audit counter has reached its safe limit."),
    "INTERNAL_ERROR": (500, "The draft service could not complete the request."),
    "NOT_FOUND": (404, "No such API route."),
    "METHOD_NOT_ALLOWED": (405, "This method is not supported."),
    "STATE_COMMIT_UNCERTAIN": (
        503,
        "Draft may have been saved; reload the workspace before retrying.",
    ),
    "REQUEST_TIMEOUT": (408, "Request body was not received within the time limit."),
    "DRAFT_LIMIT_REACHED": (409, "This draft collection has reached its 100-item limit."),
    "STATE_CORRUPT": (503, "Draft state is invalid; restore it before editing."),
    "STATE_UNAVAILABLE": (503, "Draft storage is unavailable."),
    "ORIGIN_NOT_ALLOWED": (403, "Origin is not allowed for this development workspace."),
    "HOST_NOT_ALLOWED": (403, "Only loopback development hosts are allowed."),
    "JSON_REQUIRED": (415, "Mutations require application/json with UTF-8 encoding."),
    "UNSUPPORTED_ENCODING": (415, "Encoded request bodies are unsupported."),
    "INVALID_FRAMING": (400, "Invalid request framing."),
    "BODY_TOO_LARGE": (413, "Request body exceeds the 256 KiB limit."),
    "VALIDATION_ERROR": (422, "Invalid request data."),
    "LIVE_NOT_AVAILABLE": (409, "LIVE execution is unavailable in this draft workspace."),
    "AGENT_EXECUTION_NOT_AVAILABLE": (
        409,
        "Agent execution is unavailable; preview is not inference.",
    ),
    "INVALID_REFERENCE": (422, "A referenced draft or template does not exist."),
}


class DraftError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def error_response(code: str) -> JSONResponse:
    status, message = ERRORS[code]
    return JSONResponse(status_code=status, content={"code": code, "message": message})
