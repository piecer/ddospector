"""Fixed public failures; no exception, filesystem or request values are reflected."""

from starlette.responses import JSONResponse

ERRORS = {
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
