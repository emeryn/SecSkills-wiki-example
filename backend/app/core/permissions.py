"""RBAC: roles map to permissions; every route declares an access policy or startup fails."""

from dataclasses import dataclass
from enum import StrEnum

from fastapi import FastAPI
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute, iter_route_contexts


class Permission(StrEnum):
    USERS_READ = "users:read"
    USERS_MANAGE = "users:manage"
    GROUPS_READ = "groups:read"
    GROUPS_MANAGE = "groups:manage"
    # Space settings and memberships only: administrators get no implicit read of content.
    SPACES_MANAGE = "spaces:manage"
    DASHBOARD_READ = "dashboard:read"
    AUDIT_READ = "audit:read"
    AUDIT_EXPORT = "audit:export"
    SETTINGS_MANAGE = "settings:manage"
    # Blocked IPs and honeytoken alerts.
    SECURITY_MANAGE = "security:manage"


ROLE_PERMISSIONS: dict[str, frozenset[Permission]] = {
    "user": frozenset(),
    "admin": frozenset(Permission),
}

ACTIVE = frozenset({"active"})
ANY_STATE = frozenset(
    {"active", "mfa_required", "password_change_required", "mfa_enrollment_required"}
)


@dataclass(frozen=True)
class AccessPolicy:
    """What a route requires. ``states`` lists the session states allowed to call it."""

    name: str
    authenticated: bool
    states: frozenset[str] = ACTIVE
    permission: Permission | None = None
    recent_auth: bool = False


PUBLIC = AccessPolicy("public", authenticated=False)
AUTHENTICATED = AccessPolicy("authenticated", authenticated=True)
RECENT_AUTH = AccessPolicy("recent-auth", authenticated=True, recent_auth=True)
# MCP endpoints: no session; the handler authenticates an API key and applies its scopes.
API_KEY = AccessPolicy("api-key", authenticated=False)


def session_in(states: frozenset[str], name: str) -> AccessPolicy:
    """Signed-in but possibly incomplete session (MFA, forced password change, enrollment)."""
    return AccessPolicy(name, authenticated=True, states=states)


def permission(perm: Permission, *, recent_auth: bool = False) -> AccessPolicy:
    return AccessPolicy(
        f"permission:{perm}", authenticated=True, permission=perm, recent_auth=recent_auth
    )


def _policies(dependant: Dependant) -> list[AccessPolicy]:
    found: list[AccessPolicy] = []
    for sub in dependant.dependencies:
        policy = getattr(sub.call, "policy", None)
        if isinstance(policy, AccessPolicy):
            found.append(policy)
        found.extend(_policies(sub))
    return found


def route_policies(app: FastAPI) -> dict[tuple[str, str], AccessPolicy]:
    """Map ``(method, path)`` to its policy; raises when a route declares none or several."""
    result: dict[tuple[str, str], AccessPolicy] = {}
    problems: list[str] = []
    # Included routers are nested, not flattened: walk the effective routes.
    for route in iter_route_contexts(app.routes):
        if not isinstance(route.original_route, APIRoute):
            continue
        dependant: Dependant = route.dependant
        path, methods = route.path or "", sorted(route.methods or ())
        policies = _policies(dependant)
        if len(policies) != 1:
            problems.append(f"{methods} {path}: {len(policies)} access policies")
            continue
        for method in methods:
            result[(method, path)] = policies[0]
    if not result:
        raise RuntimeError("No API routes found: route enumeration is broken")
    if problems:
        raise RuntimeError(
            "Every route must declare exactly one access policy: " + "; ".join(problems)
        )
    return result
