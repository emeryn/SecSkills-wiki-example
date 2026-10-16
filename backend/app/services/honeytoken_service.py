"""Honeytokens: decoy usernames and a trap endpoint no legitimate client ever calls.

A hit records a critical audit event (forwarded to syslog and the notifications) and blocks the
client IP. The IP is blocked only when it is attributable to the client: with a wrong trusted
proxy count the peer would be the reverse proxy, and blocking it would lock everyone out.
"""

import ipaddress
import logging
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.context import AppContext
from app.core.crypto import normalize
from app.core.errors import AppError
from app.models import BlockedIp
from app.repositories import users as user_repo
from app.services import audit_service
from app.services.audit_service import Actor

logger = logging.getLogger(__name__)

Kind = Literal["decoy_login", "trap_endpoint"]


def is_decoy(db: Session, ctx: AppContext, username: str) -> bool:
    """A decoy name with no real account behind it (a real account always wins)."""
    security = ctx.runtime.snapshot().security
    if not security.honeytokens_enabled:
        return False
    decoys = {normalize(name) for name in security.decoy_usernames}
    return normalize(username) in decoys and user_repo.find_by_username(db, username) is None


def _blockable(actor: Actor) -> bool:
    if actor.ip is None or not actor.ip_trusted:
        return False
    address = ipaddress.ip_address(actor.ip)
    return not (address.is_loopback or address.is_unspecified)


def trigger(db: Session, ctx: AppContext, actor: Actor, kind: Kind, detail: dict[str, Any]) -> None:
    """Record the hit and block the client IP; the caller commits."""
    security = ctx.runtime.snapshot().security
    blocked = _blockable(actor)
    if blocked and actor.ip is not None:
        now = datetime.now(UTC)
        expires = (
            now + timedelta(minutes=security.block_minutes) if security.block_minutes else None
        )
        statement = insert(BlockedIp).values(
            ip=actor.ip, reason=kind, hits=1, blocked_at=now, expires_at=expires
        )
        db.execute(
            statement.on_conflict_do_update(
                index_elements=[BlockedIp.ip],
                set_={
                    "hits": BlockedIp.hits + 1,
                    "reason": kind,
                    "blocked_at": now,
                    "expires_at": expires,
                },
            )
        )
        ctx.blocklist.add(actor.ip, expires)
    else:
        logger.error(
            "Honeytoken hit from an unattributable IP; check BACKEND_TRUSTED_PROXY_COUNT",
            extra={"kind": kind},
        )
    audit_service.record(
        db,
        actor,
        "security.honeytoken",
        outcome="failure",
        severity="critical",
        target_type="ip",
        target_id=actor.ip,
        after={"kind": kind, "blocked": blocked, **detail},
    )


def list_blocked(db: Session) -> list[BlockedIp]:
    now = datetime.now(UTC)
    return list(
        db.scalars(
            select(BlockedIp)
            .where((BlockedIp.expires_at.is_(None)) | (BlockedIp.expires_at > now))
            .order_by(BlockedIp.blocked_at.desc())
            .limit(500)
        ).all()
    )


def unblock(db: Session, ctx: AppContext, ip: str, actor: Actor) -> None:
    try:
        address = str(ipaddress.ip_address(ip))
    except ValueError as exc:
        raise AppError(404, "NOT_FOUND", "Not found") from exc
    row = db.get(BlockedIp, address)
    if row is None:
        raise AppError(404, "NOT_FOUND", "Not found")
    db.execute(delete(BlockedIp).where(BlockedIp.ip == address))
    ctx.blocklist.remove(address)
    audit_service.record(
        db,
        actor,
        "security.ip_unblocked",
        target_type="ip",
        target_id=address,
        before={"reason": row.reason, "hits": row.hits},
    )
    db.commit()
