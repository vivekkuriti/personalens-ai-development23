"""URL validation and network safety: block private networks, metadata endpoints and off-domain navigation."""
from __future__ import annotations

import ipaddress
import socket
from functools import lru_cache
from urllib.parse import urlparse

BLOCKED_HOSTNAMES = {
    "localhost",
    "metadata",
    "metadata.google.internal",
    "metadata.azure.com",
    "instance-data",
    "instance-data.ec2.internal",
}
BLOCKED_SUFFIXES = (".localhost", ".local", ".internal", ".lan", ".home", ".corp", ".intranet")
METADATA_IPS = {
    ipaddress.ip_address("169.254.169.254"),
    ipaddress.ip_address("169.254.170.2"),
    ipaddress.ip_address("100.100.100.200"),
    ipaddress.ip_address("fd00:ec2::254"),
}
TWO_LEVEL_TLDS = {"co", "com", "org", "net", "gov", "ac", "edu"}


class URLValidationError(ValueError):
    pass


def is_ip_blocked(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True
    if getattr(ip, "ipv4_mapped", None):
        ip = ip.ipv4_mapped
    return (
        ip in METADATA_IPS
        or ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or (ip.version == 4 and ip in ipaddress.ip_network("100.64.0.0/10"))
    )


@lru_cache(maxsize=1024)
def _resolve(host: str) -> tuple[str, ...]:
    try:
        infos = socket.getaddrinfo(host, None)
    except (socket.gaierror, UnicodeError, OSError):
        return ()
    return tuple(sorted({info[4][0] for info in infos}))


def is_host_safe(host: str | None) -> bool:
    if not host:
        return False
    host = host.lower().strip(".").strip("[]")
    if host in BLOCKED_HOSTNAMES or host.endswith(BLOCKED_SUFFIXES):
        return False
    try:
        ipaddress.ip_address(host)
        return not is_ip_blocked(host)
    except ValueError:
        pass
    addresses = _resolve(host)
    if not addresses:
        return False
    return all(not is_ip_blocked(a) for a in addresses)


def normalize_url(raw: str) -> str:
    url = (raw or "").strip()
    if not url:
        raise URLValidationError("Please enter a website URL.")
    if "://" not in url:
        url = "https://" + url
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise URLValidationError("Only http:// and https:// URLs can be tested.")
    if not parsed.hostname:
        raise URLValidationError("The URL must include a valid hostname.")
    if parsed.username or parsed.password:
        raise URLValidationError("URLs with embedded credentials are not allowed.")
    if "." not in parsed.hostname and not _is_ip_literal(parsed.hostname):
        raise URLValidationError("The hostname must be a public domain (e.g. example.com).")
    return parsed.geturl()


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host.strip("[]"))
        return True
    except ValueError:
        return False


def validate_target_url(raw: str) -> str:
    """Normalize and validate a user-supplied target URL. Raises URLValidationError."""
    url = normalize_url(raw)
    host = urlparse(url).hostname
    if not is_host_safe(host):
        raise URLValidationError(
            f"'{host}' resolves to a private, local, or metadata address, or could not be resolved. "
            "Only public websites can be tested."
        )
    return url


def registrable_domain(host: str) -> str:
    host = host.lower().strip(".")
    if _is_ip_literal(host):
        return host
    labels = host.split(".")
    if len(labels) >= 3 and len(labels[-1]) == 2 and labels[-2] in TWO_LEVEL_TLDS:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:]) if len(labels) >= 2 else host


def allowed_domains_for(url: str) -> set[str]:
    host = (urlparse(url).hostname or "").lower()
    return {host, registrable_domain(host)} if host else set()


def is_domain_allowed(host: str | None, allowed: set[str]) -> bool:
    if not host:
        return False
    host = host.lower().strip(".")
    return any(host == d or host.endswith("." + d) for d in allowed)


def is_navigation_allowed(url: str, allowed: set[str]) -> bool:
    parsed = urlparse(url)
    if parsed.scheme in {"about", "data", "blob"}:
        return True
    if parsed.scheme not in {"http", "https"}:
        return False
    return is_domain_allowed(parsed.hostname, allowed) and is_host_safe(parsed.hostname)
