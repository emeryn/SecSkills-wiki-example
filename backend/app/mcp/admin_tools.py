"""Administration MCP tools (``/mcp/admin``): off by default, admin-scoped keys only.

Read tools list users, audit events and blocked IPs. Destructive tools (unblocking an IP, signing
a user out everywhere) require ``confirm: true``. Nothing here reads page content: administrators
have no implicit access to restricted spaces, through MCP neither.
"""

import uuid
from typing import Any, Literal

from pydantic import Field

from app.core.errors import AppError
from app.mcp.server import ConfirmArgs, Tool, ToolContext, registry
from app.repositories import audit as audit_repo
from app.repositories import users as user_repo
from app.schemas.audit import AuditFilters
from app.schemas.common import StrictModel
from app.services import honeytoken_service, user_admin_service

INSTRUCTIONS = (
    "Administration tools of an internal wiki. Destructive tools need confirm=true: ask the human "
    "operator before setting it."
)


class ListUsersArgs(StrictModel):
    username_prefix: str | None = Field(None, max_length=64, pattern=r"^[A-Za-z0-9._-]*$")
    status: Literal["active", "disabled"] | None = None
    limit: int = Field(25, ge=1, le=100)


class ListAuditArgs(AuditFilters):
    limit: int = Field(50, ge=1, le=100)


class EmptyArgs(StrictModel):
    pass


class UnblockArgs(ConfirmArgs):
    ip: str = Field(max_length=45, pattern=r"^[0-9A-Fa-f:.]+$")


class RevokeSessionsArgs(ConfirmArgs):
    user_id: uuid.UUID


def list_users(c: ToolContext, args: ListUsersArgs) -> dict[str, Any]:
    users, total = user_repo.search_users(
        c.db,
        username_prefix=args.username_prefix or None,
        email_bidx=None,
        role=None,
        status=args.status,
        sort="username",
        descending=False,
        page=1,
        page_size=args.limit,
    )
    return {
        "total": total,
        "users": [
            {
                "id": str(u.id),
                "username": u.username,
                "role": u.global_role,
                "status": u.status,
                "auth_source": u.auth_source,
                "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
            }
            for u in users
        ],
    }


def list_audit_events(c: ToolContext, args: ListAuditArgs) -> dict[str, Any]:
    filters = AuditFilters.model_validate(args.model_dump(exclude={"limit"}))
    rows, total = audit_repo.page(c.db, filters, 1, args.limit)
    return {
        "total": total,
        "events": [
            {
                "id": event.id,
                "occurred_at": event.occurred_at.isoformat(),
                "actor": username,
                "action": event.action,
                "outcome": event.outcome,
                "severity": event.severity,
                "target": f"{event.target_type}:{event.target_id}" if event.target_type else None,
                "ip": str(event.actor_ip) if event.actor_ip else None,
            }
            for event, username in rows
        ],
    }


def list_blocked_ips(c: ToolContext, args: EmptyArgs) -> dict[str, Any]:
    return {
        "blocked": [
            {
                "ip": str(row.ip),
                "reason": row.reason,
                "hits": row.hits,
                "expires_at": row.expires_at.isoformat() if row.expires_at else None,
            }
            for row in honeytoken_service.list_blocked(c.db)
        ]
    }


def unblock_ip(c: ToolContext, args: UnblockArgs) -> dict[str, Any]:
    honeytoken_service.unblock(c.db, c.ctx, args.ip, c.actor)
    return {"unblocked": args.ip}


def revoke_user_sessions(c: ToolContext, args: RevokeSessionsArgs) -> dict[str, Any]:
    user = user_repo.get(c.db, args.user_id)
    if user is None:
        raise AppError(404, "NOT_FOUND", "Not found")
    return {"revoked_sessions": user_admin_service.revoke_sessions(c.db, user, c.actor)}


ADMIN_TOOLS = registry(
    Tool("list_users", "List accounts (no personal data).", ListUsersArgs, "admin", list_users),
    Tool(
        "list_audit_events",
        "Latest audit events, filtered like the audit viewer.",
        ListAuditArgs,
        "admin",
        list_audit_events,
    ),
    Tool(
        "list_blocked_ips",
        "Client IPs blocked by honeytokens.",
        EmptyArgs,
        "admin",
        list_blocked_ips,
    ),
    Tool(
        "unblock_ip",
        "Unblock a client IP. Destructive: requires confirm=true.",
        UnblockArgs,
        "admin",
        unblock_ip,
        destructive=True,
    ),
    Tool(
        "revoke_user_sessions",
        "Sign a user out everywhere. Destructive: requires confirm=true.",
        RevokeSessionsArgs,
        "admin",
        revoke_user_sessions,
        destructive=True,
    ),
)
