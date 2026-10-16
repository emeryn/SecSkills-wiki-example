"""Directory sign-in over LDAPS or StartTLS.

The user is looked up with the service account, then authenticated by binding as their own entry.
Every value placed in a filter is escaped (RFC 4515): an injected ``*)(uid=*`` matches nothing.
An empty password is refused before any bind (it would be an unauthenticated bind, which many
servers accept). StartTLS happens before any credentials are sent; certificates are verified.
"""

import logging
import ssl
from collections.abc import Callable
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from ldap3 import NONE, SUBTREE, Connection, Server, Tls
from ldap3.core.exceptions import LDAPException
from ldap3.utils.conv import escape_filter_chars

from app.core.outbound_url import Network, resolve
from app.schemas.settings import LdapSettings

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 5
MAX_GROUPS = 500


class DirectoryUnavailableError(RuntimeError):
    """The directory could not be reached or the service account was refused."""


@dataclass(frozen=True)
class DirectoryUser:
    dn: str
    external_id: str
    username: str
    email: str | None
    display_name: str | None
    groups: list[str] = field(default_factory=list)


ConnectionFactory = Callable[[LdapSettings, list[Network], str | None, str | None], Connection]


def connect(
    config: LdapSettings, allowed: list[Network], user: str | None, password: str | None
) -> Connection:
    """Bound connection (StartTLS first when configured); raises ``LDAPException``."""
    if config.url is None:
        raise DirectoryUnavailableError("No directory configured")
    parts = urlsplit(config.url)
    secure = parts.scheme == "ldaps"
    destination = resolve(parts.hostname or "", parts.port or (636 if secure else 389), allowed)
    tls = Tls(
        validate=ssl.CERT_REQUIRED,
        version=ssl.PROTOCOL_TLS_CLIENT,
        ca_certs_data=config.ca_pem,
        valid_names=[destination.host],
        sni=destination.host,
    )
    server = Server(
        destination.address,
        port=destination.port,
        use_ssl=secure,
        tls=tls,
        get_info=NONE,
        connect_timeout=TIMEOUT_SECONDS,
    )
    connection = Connection(
        server, user=user, password=password, receive_timeout=TIMEOUT_SECONDS, read_only=True
    )
    connection.open()
    if config.start_tls and not connection.start_tls():
        raise DirectoryUnavailableError("StartTLS failed")
    if not connection.bind():
        connection.unbind()
        raise DirectoryUnavailableError("Bind refused")
    return connection


def user_filter(config: LdapSettings, username: str) -> str:
    return config.user_filter.replace("{username}", escape_filter_chars(username))


def group_filter(config: LdapSettings, user_dn: str) -> str:
    return config.group_filter.replace("{user_dn}", escape_filter_chars(user_dn))


def _first(entry: object, attribute: str) -> str | None:
    values = getattr(entry, "entry_attributes_as_dict", {}).get(attribute) or []
    return str(values[0]) if values else None


def _groups(
    connection: Connection, config: LdapSettings, user_dn: str, member_of: list[str]
) -> list[str]:
    groups = list(member_of)
    if config.group_base_dn:
        connection.search(
            config.group_base_dn,
            group_filter(config, user_dn),
            SUBTREE,
            attributes=["cn"],
            size_limit=MAX_GROUPS,
        )
        for entry in connection.entries:
            groups.append(entry.entry_dn)
            name = _first(entry, "cn")
            if name:
                groups.append(name)
    return groups


def _service(
    config: LdapSettings, allowed: list[Network], factory: ConnectionFactory | None
) -> Connection:
    try:
        return (factory or connect)(config, allowed, config.bind_dn, config.bind_password)
    except (LDAPException, OSError) as exc:
        raise DirectoryUnavailableError("The directory is unreachable") from exc


def find_user(
    config: LdapSettings,
    allowed: list[Network],
    username: str,
    factory: ConnectionFactory | None = None,
) -> tuple[str, dict[str, list[str]]] | None:
    """``(dn, attributes)`` of the only entry matching ``username``, or None."""
    connection = _service(config, allowed, factory)
    try:
        attributes = [
            config.username_attribute,
            config.email_attribute,
            config.name_attribute,
            "entryUUID",
            "objectGUID",
            "memberOf",
        ]
        connection.search(
            config.user_base_dn or "",
            user_filter(config, username),
            SUBTREE,
            attributes=attributes,
            size_limit=2,
        )
        entries = list(connection.entries)
        # Zero or several matches: refuse rather than guess.
        if len(entries) != 1:
            return None
        entry = entries[0]
        values = {
            name: [str(v) for v in vals] for name, vals in entry.entry_attributes_as_dict.items()
        }
        return entry.entry_dn, values
    except LDAPException as exc:
        raise DirectoryUnavailableError("Directory search failed") from exc
    finally:
        connection.unbind()


def authenticate(
    config: LdapSettings,
    allowed: list[Network],
    username: str,
    password: str,
    factory: ConnectionFactory | None = None,
) -> DirectoryUser | None:
    """The directory user when ``password`` is theirs, else None."""
    if not password or not username:
        return None
    found = find_user(config, allowed, username, factory)
    if found is None:
        return None
    dn, values = found
    try:
        user_connection = (factory or connect)(config, allowed, dn, password)
    except DirectoryUnavailableError:
        return None
    except (LDAPException, OSError) as exc:
        raise DirectoryUnavailableError("The directory is unreachable") from exc
    user_connection.unbind()
    # Groups are read with the service account: directories rarely let users read group entries.
    service = _service(config, allowed, factory)
    try:
        groups = _groups(service, config, dn, values.get("memberOf", []))
    except LDAPException:
        logger.warning("Directory group lookup failed; no group memberships applied")
        groups = []
    finally:
        service.unbind()

    def first(name: str) -> str | None:
        found_values = values.get(name) or []
        return found_values[0] if found_values else None

    stable_id = first("entryUUID") or first("objectGUID") or dn
    return DirectoryUser(
        dn=dn,
        external_id=stable_id[:255],
        username=first(config.username_attribute) or username,
        email=first(config.email_attribute),
        display_name=first(config.name_attribute),
        groups=groups,
    )


def check(
    config: LdapSettings, allowed: list[Network], factory: ConnectionFactory | None = None
) -> str:
    """Bind with the service account and run a sample search; returns a summary."""
    connection = _service(config, allowed, factory)
    try:
        connection.search(
            config.user_base_dn or "",
            user_filter(config, "*").replace(escape_filter_chars("*"), "*"),
            SUBTREE,
            attributes=[],
            size_limit=5,
        )
        users = len(connection.entries)
        groups = 0
        if config.group_base_dn:
            connection.search(
                config.group_base_dn, "(objectClass=*)", SUBTREE, attributes=[], size_limit=5
            )
            groups = len(connection.entries)
    except LDAPException as exc:
        raise DirectoryUnavailableError("Directory search failed") from exc
    finally:
        connection.unbind()
    return f"Bind succeeded; sample search found {users} user(s) and {groups} group entr(ies)"
