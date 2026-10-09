"""Bounded syntactic validation only: addresses are never resolved or contacted."""

import ipaddress
import re
import unicodedata
from typing import Annotated
from urllib.parse import urlsplit

from pydantic import AfterValidator, StringConstraints


def checked_text(value: str, *, multiline: bool = False) -> str:
    if not value.strip() or any(
        unicodedata.category(character) in {"Cc", "Cf", "Cs"}
        and not (multiline and character in "\n\r\t")
        for character in value
    ):
        raise ValueError("Invalid text")
    return value


def multiline_text(value: str) -> str:
    return checked_text(value, multiline=True)


Name = Annotated[str, StringConstraints(min_length=1, max_length=120), AfterValidator(checked_text)]
Description = Annotated[
    str,
    StringConstraints(min_length=1, max_length=1000),
    AfterValidator(multiline_text),
]
Instructions = Annotated[
    str,
    StringConstraints(min_length=1, max_length=8000),
    AfterValidator(multiline_text),
]
Goal = Annotated[
    str, StringConstraints(min_length=1, max_length=2000), AfterValidator(multiline_text)
]
Identifier = Annotated[str, StringConstraints(min_length=1, max_length=64, pattern=r"^[a-z0-9-]+$")]


def address_literal(value: str) -> str:
    checked_text(value)
    if "%" in value:
        raise ValueError("Scoped addresses are not supported")
    try:
        ipaddress.ip_address(value)
        return value
    except ValueError:
        pass
    hostname = value[:-1] if value.endswith(".") else value
    if len(hostname) > 253 or re.fullmatch(r"[0-9.]+", hostname):
        raise ValueError("Invalid address")
    labels = hostname.split(".")
    if not all(re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", p) for p in labels):
        raise ValueError("Invalid hostname")
    return value


Address = Annotated[
    str,
    StringConstraints(min_length=1, max_length=255),
    AfterValidator(address_literal),
]
Endpoint = Annotated[
    str,
    StringConstraints(min_length=1, max_length=512),
    AfterValidator(checked_text),
]


def endpoint_literal(value: str, transport: str) -> str:
    if transport == "stdio":
        if not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", value):
            raise ValueError("Expected a registered identifier, not a command")
        return value
    if "\\" in value or any(character.isspace() for character in value):
        raise ValueError("Invalid endpoint")
    url = urlsplit(value)
    if (
        url.scheme not in {"http", "https"}
        or not url.hostname
        or url.username is not None
        or url.password is not None
        or "#" in value
        or "?" in value
    ):
        # Query strings are deliberately unsupported: this store has no credential facility.
        raise ValueError("Expected a credential-free HTTP endpoint")
    address_literal(url.hostname)
    if url.port is not None and not 1 <= url.port <= 65535:
        raise ValueError("Invalid endpoint port")
    return value


def unique_ids(value: list[str]) -> list[str]:
    if len(value) != len(set(value)):
        raise ValueError("Duplicate assignment")
    return value
