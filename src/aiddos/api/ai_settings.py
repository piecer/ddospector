"""AI draft validation only; no credentials, provider clients or execution."""

import ipaddress
import re
from typing import Annotated
from urllib.parse import urlsplit

from pydantic import AfterValidator, StringConstraints

from .validation import address_literal, checked_text


def literal_text(value: str) -> str:
    checked_text(value)
    if value != value.strip():
        raise ValueError("Surrounding whitespace is not allowed")
    return value


AIIdentifier = Annotated[
    str, StringConstraints(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_-]*$")
]
AIName = Annotated[
    str, StringConstraints(min_length=1, max_length=120), AfterValidator(literal_text)
]
AIModel = Annotated[
    str, StringConstraints(min_length=1, max_length=200), AfterValidator(literal_text)
]
CredentialReference = Annotated[
    str, StringConstraints(max_length=64, pattern=r"^(?:[A-Z][A-Z0-9_]*|)$")
]


def base_url_literal(value: str) -> str:
    if not value:
        return value
    checked_text(value)
    if any(character.isspace() for character in value) or any(c in value for c in "\\?#"):
        raise ValueError("Invalid draft URL")
    url = urlsplit(value)
    if (
        url.scheme not in {"http", "https"}
        or not url.hostname
        or "@" in url.netloc
        or "%" in url.netloc
    ):
        raise ValueError("Expected a credential-free absolute HTTP URL")
    if url.netloc.startswith("["):
        # urlsplit alone accepts trailing junk after a bracketed host.
        authority = re.fullmatch(r"\[([^\]]+)\](?::([0-9]+))?", url.netloc)
        if authority is None:
            raise ValueError("Invalid IPv6 authority")
        ipaddress.IPv6Address(authority[1])
    else:
        authority = re.fullmatch(r"([^:]+)(?::([0-9]+))?", url.netloc)
        if authority is None:
            raise ValueError("Invalid authority")
        # Syntactic IDNA validation only; retain the operator's literal URL.
        address_literal(authority[1].encode("idna").decode("ascii"))
    if url.port is not None and not 1 <= url.port <= 65535:
        raise ValueError("Invalid port")
    return value


AIBaseURL = Annotated[str, StringConstraints(max_length=512), AfterValidator(base_url_literal)]
