"""Effective single sign-on configuration: environment variables over values saved in the UI."""

import ipaddress
from typing import Literal

from app.core.context import AppContext
from app.core.outbound_url import Network, OutboundUrlError, parse_networks
from app.schemas.settings import LdapSettings, OidcSettings

SsoSection = Literal["oidc", "ldap"]
# Destination fields: when the operator sets them, private networks are trusted (loopback,
# link-local and metadata stay refused); from the UI they must be allowlisted in Security.
_DESTINATION = {"oidc": "issuer", "ldap": "url"}
_PRIVATE = tuple(
    ipaddress.ip_network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fc00::/7")
)


def oidc(ctx: AppContext) -> OidcSettings:
    stored = ctx.runtime.snapshot().oidc.model_dump()
    return OidcSettings.model_validate({**stored, **ctx.sso_env.values("oidc")})


def ldap(ctx: AppContext) -> LdapSettings:
    stored = ctx.runtime.snapshot().ldap.model_dump()
    return LdapSettings.model_validate({**stored, **ctx.sso_env.values("ldap")})


def managed_fields(ctx: AppContext, section: str) -> frozenset[str]:
    return ctx.sso_env.managed(section)


def allowed_networks(ctx: AppContext, section: SsoSection) -> list[Network]:
    if _DESTINATION[section] in ctx.sso_env.managed(section):
        return list(_PRIVATE)
    try:
        return parse_networks(ctx.runtime.snapshot().security.allowed_private_networks)
    except OutboundUrlError:
        return []


def effective(ctx: AppContext, section: SsoSection) -> OidcSettings | LdapSettings:
    return oidc(ctx) if section == "oidc" else ldap(ctx)
