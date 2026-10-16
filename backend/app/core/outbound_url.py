"""SSRF guard for every destination an administrator can configure (syslog, SMTP, webhooks).

The host is resolved once and every address it resolves to must be public, or inside a private
network the administrator explicitly allowlisted. Loopback, link-local (cloud metadata included),
multicast and reserved ranges are never reachable. Callers connect to the returned address, not
to the name, so a second DNS answer cannot redirect the connection (DNS rebinding).
"""

import ipaddress
import re
import socket
import ssl
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

Address = ipaddress.IPv4Address | ipaddress.IPv6Address
Network = ipaddress.IPv4Network | ipaddress.IPv6Network
Resolver = Callable[[str, int], list[str]]

MAX_URL_LENGTH = 2000
_HOSTNAME = re.compile(
    r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*$"
)
# Unreachable whatever the allowlist says: metadata services live in link-local space.
_NEVER = tuple(
    ipaddress.ip_network(n)
    for n in ("0.0.0.0/8", "169.254.0.0/16", "fe80::/10", "fd00:ec2::254/128")
)


class OutboundUrlError(ValueError):
    """The destination is refused; ``reason`` is safe to show to an administrator."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class Destination:
    """Validated destination: connect to ``address``, verify TLS and send ``Host`` for ``host``."""

    host: str
    port: int
    address: str
    path: str = "/"


def tls_context(ca_pem: str | None = None, ca_file: Path | None = None) -> ssl.SSLContext:
    """Verifying client context; an internal CA is added, verification is never disabled."""
    context = ssl.create_default_context(
        cafile=str(ca_file) if ca_file else None, cadata=ca_pem or None
    )
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    return context


def system_resolver(host: str, port: int) -> list[str]:
    """Every address the system resolver returns for ``host`` (TCP)."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError) as exc:
        raise OutboundUrlError("The host name could not be resolved") from exc
    return list(dict.fromkeys(str(info[4][0]) for info in infos))


def parse_networks(values: Iterable[str]) -> list[Network]:
    """Parse an allowlist of private networks; public, loopback or link-local ones are refused."""
    networks: list[Network] = []
    for value in values:
        try:
            network = ipaddress.ip_network(value.strip(), strict=False)
        except ValueError as exc:
            raise OutboundUrlError(f"Invalid network: {value}") from exc
        if not network.is_private or network.is_loopback or network.is_link_local:
            raise OutboundUrlError(f"Only private networks can be allowlisted: {value}")
        # Wider networks may contain a never-reachable address: ``check_address`` still refuses it.
        if any(
            network.version == never.version and network.subnet_of(never)  # type: ignore[arg-type]
            for never in _NEVER
        ):
            raise OutboundUrlError(f"This network can never be allowlisted: {value}")
        networks.append(network)
    return networks


def check_address(raw: str, allowed: Iterable[Network]) -> Address:
    """Return the address if a connection to it is permitted, else raise ``OutboundUrlError``."""
    address = ipaddress.ip_address(raw.split("%", 1)[0])
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    if (
        address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_unspecified
        or address.is_reserved
        or any(address in network for network in _NEVER)
    ):
        raise OutboundUrlError("This address is not allowed (loopback, link-local or reserved)")
    if address.is_global:
        return address
    if any(address in network for network in allowed):
        return address
    raise OutboundUrlError(
        "Private addresses are refused unless their network is allowlisted in Security settings"
    )


def normalize_host(host: str) -> str:
    """Lower-cased host name or IP literal; refuses anything else (userinfo, spaces, IDN tricks)."""
    candidate = host.strip().lower().rstrip(".")
    try:
        return str(ipaddress.ip_address(candidate.strip("[]")))
    except ValueError:
        pass
    try:
        candidate = candidate.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise OutboundUrlError("Invalid host name") from exc
    if not _HOSTNAME.match(candidate):
        raise OutboundUrlError("Invalid host name")
    return candidate


def resolve(
    host: str,
    port: int,
    allowed: Iterable[Network] = (),
    resolver: Resolver | None = None,
    path: str = "/",
) -> Destination:
    """Resolve and check every address; the first one is pinned for the connection."""
    if not 1 <= port <= 65535:  # noqa: PLR2004
        raise OutboundUrlError("Invalid port")
    name = normalize_host(host)
    allowed = list(allowed)
    try:
        addresses = [str(ipaddress.ip_address(name))]
    except ValueError:
        addresses = (resolver or system_resolver)(name, port)
    if not addresses:
        raise OutboundUrlError("The host name could not be resolved")
    # One refused answer is enough to refuse: an attacker controls which answer is used next.
    checked = [check_address(address, allowed) for address in addresses]
    return Destination(host=name, port=port, address=str(checked[0]), path=path)


def resolve_url(
    url: str, allowed: Iterable[Network] = (), resolver: Resolver | None = None
) -> Destination:
    """Validate an ``https`` URL (no credentials, no fragment) and resolve its host."""
    if len(url) > MAX_URL_LENGTH:
        raise OutboundUrlError("URL too long")
    parts = urlsplit(url.strip())
    if parts.scheme != "https":
        raise OutboundUrlError("Only https URLs are allowed")
    if parts.username is not None or parts.password is not None or "@" in parts.netloc:
        raise OutboundUrlError("Credentials in the URL are not allowed")
    if parts.fragment:
        raise OutboundUrlError("Fragments are not allowed")
    try:
        port = parts.port or 443
    except ValueError as exc:
        raise OutboundUrlError("Invalid port") from exc
    if not parts.hostname:
        raise OutboundUrlError("The URL has no host")
    path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
    return resolve(parts.hostname, port, allowed, resolver, path=path)
