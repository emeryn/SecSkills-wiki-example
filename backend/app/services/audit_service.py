"""Tamper-evident audit trail.

Rows are written under a transaction-scoped advisory lock so the chain stays linear; each hash
covers the previous hash and the canonical JSON of the row. ``verify_chain`` recomputes it.
"""

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import AuditEvent

logger = logging.getLogger("app.audit")

GENESIS_HASH = b"\x00" * 32
_CHAIN_LOCK_ID = 0x5717_A0D1
_LOG_LEVELS = {"info": logging.INFO, "warning": logging.WARNING, "critical": logging.CRITICAL}


@dataclass(frozen=True)
class Actor:
    """Who performed an action and from where."""

    user_id: uuid.UUID | None
    ip: str | None
    user_agent: str
    request_id: str | None
    # True when ``ip`` is attributable to the client (see ``core.middleware.client_ip_trusted``).
    ip_trusted: bool = False


SYSTEM = Actor(user_id=None, ip=None, user_agent="system", request_id=None)


def _canonical(event: AuditEvent) -> bytes:
    payload: dict[str, Any] = {
        "occurred_at": event.occurred_at.astimezone(UTC).isoformat(),
        "actor_user_id": str(event.actor_user_id) if event.actor_user_id else None,
        "actor_ip": str(event.actor_ip) if event.actor_ip else None,
        "user_agent": event.user_agent,
        "action": event.action,
        "outcome": event.outcome,
        "target_type": event.target_type,
        "target_id": event.target_id,
        "before": event.before,
        "after": event.after,
        "request_id": event.request_id,
    }
    # Info rows hash without the field, so chains written before it existed still verify.
    if event.severity not in (None, "info"):
        payload["severity"] = event.severity
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()


def _hash(prev_hash: bytes, event: AuditEvent) -> bytes:
    return hashlib.sha256(prev_hash + _canonical(event)).digest()


def record(
    db: Session,
    actor: Actor,
    action: str,
    *,
    outcome: str = "success",
    severity: str = "info",
    target_type: str | None = None,
    target_id: object = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
) -> AuditEvent:
    """Append an event in the caller's transaction; the caller commits."""
    db.execute(text("SELECT pg_advisory_xact_lock(:id)"), {"id": _CHAIN_LOCK_ID})
    prev_hash = db.scalar(select(AuditEvent.hash).order_by(AuditEvent.id.desc()).limit(1))
    event = AuditEvent(
        occurred_at=datetime.now(UTC),
        actor_user_id=actor.user_id,
        actor_ip=actor.ip,
        user_agent=actor.user_agent[:512],
        action=action,
        outcome=outcome,
        severity=severity,
        target_type=target_type,
        target_id=str(target_id) if target_id is not None else None,
        before=before,
        after=after,
        request_id=actor.request_id,
        prev_hash=prev_hash or GENESIS_HASH,
    )
    event.hash = _hash(event.prev_hash, event)
    db.add(event)
    db.flush()
    # Critical events reach the error notifications (email, webhook) through the log level.
    logger.log(
        _LOG_LEVELS[severity],
        "audit",
        extra={
            "audit_action": action,
            "audit_outcome": outcome,
            "audit_severity": severity,
            "audit_target": f"{target_type}:{event.target_id}" if target_type else None,
            "actor_user_id": str(actor.user_id) if actor.user_id else None,
        },
    )
    return event


def verify_chain(db: Session, batch_size: int = 1000) -> int | None:
    """Return the id of the first row whose hash does not match, or None if the chain is intact."""
    prev_hash = GENESIS_HASH
    last_id = 0
    while True:
        rows = db.scalars(
            select(AuditEvent)
            .where(AuditEvent.id > last_id)
            .order_by(AuditEvent.id)
            .limit(batch_size)
        ).all()
        if not rows:
            return None
        for event in rows:
            if event.prev_hash != prev_hash or event.hash != _hash(prev_hash, event):
                return event.id
            prev_hash = event.hash
            last_id = event.id
