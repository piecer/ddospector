"""Explicit, per-application opt-in for unauthenticated LAN development."""

import ipaddress
import logging
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from aiddos.startup import startup_setting


@dataclass(frozen=True)
class DevelopmentAccess:
    origin: str | None = None
    authority: str | None = None


def development_access() -> DevelopmentAccess:
    flag = startup_setting("ALLOW_INSECURE_DEV")
    if flag in (None, "", "0"):
        return DevelopmentAccess()
    if flag != "1":
        raise ValueError("DDOSPECTOR_ALLOW_INSECURE_DEV must be 0 or 1")
    origin = startup_setting("DEV_ORIGIN") or ""
    error = "DDOSPECTOR_DEV_ORIGIN must be an exact http(s)://host:port with non-default port"
    if len(origin) > 300 or not re.fullmatch(r"https?://[^/?#\s]+", origin, re.ASCII):
        raise ValueError(error)
    try:
        parsed = urlsplit(origin)
        host, port = parsed.hostname, parsed.port
        if (
            not host or not port or "%" in host
            or port == (80 if parsed.scheme == "http" else 443)
            or parsed.username is not None or parsed.password is not None
        ):
            raise ValueError(error)
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            if not re.fullmatch(
                r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
                r"(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*", host
            ) or re.fullmatch(r"[0-9.]+", host) or len(host) > 253:
                raise ValueError(error) from None
            literal = host
        else:
            if str(address) != host or address.is_unspecified or address.is_multicast:
                raise ValueError(error)
            literal = f"[{host}]" if address.version == 6 else host
        authority = f"{literal}:{port}"
        if origin != f"{parsed.scheme}://{authority}":
            raise ValueError(error)
    except ValueError:
        raise ValueError(error) from None
    logging.getLogger(__name__).warning(
        "INSECURE DEVELOPMENT ACCESS enabled: one additional Host/Origin is allowed; "
        "there is NO authentication. Trusted isolated development only. "
        "LIVE execution and approval restrictions remain enforced."
    )
    return DevelopmentAccess(origin, authority)
