"""Audit trail queries for the administration viewer and CSV export (read-only)."""

import uuid
from collections.abc import Iterator
from typing import Any

from sqlalchemy import Select, and_, cast, func, select
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.orm import Session

from app.models import AuditEvent, User
from app.schemas.audit import AuditFilters

SYSTEM_ACTOR = "system"
_NO_MATCH = uuid.UUID(int=0)


def _actor_condition(db: Session, actor: str) -> Any:
    if actor.lower() == SYSTEM_ACTOR:
        return and_(AuditEvent.actor_user_id.is_(None), AuditEvent.user_agent == SYSTEM_ACTOR)
    user_id = db.scalar(select(User.id).where(func.lower(User.username) == actor.lower()))
    return AuditEvent.actor_user_id == (user_id or _NO_MATCH)


def filtered(db: Session, filters: AuditFilters) -> Select[AuditEvent, str]:
    query = select(AuditEvent, User.username).outerjoin(User, User.id == AuditEvent.actor_user_id)
    if filters.action:
        if filters.action.endswith("."):
            escaped = filters.action.replace("_", r"\_")
            query = query.where(AuditEvent.action.like(f"{escaped}%", escape="\\"))
        else:
            query = query.where(AuditEvent.action == filters.action)
    if filters.actor:
        query = query.where(_actor_condition(db, filters.actor))
    if filters.outcome:
        query = query.where(AuditEvent.outcome == filters.outcome)
    if filters.severity:
        query = query.where(AuditEvent.severity == filters.severity)
    if filters.target_type:
        query = query.where(AuditEvent.target_type == filters.target_type)
    if filters.target_id:
        query = query.where(AuditEvent.target_id == filters.target_id)
    if filters.ip:
        query = query.where(AuditEvent.actor_ip == cast(filters.ip, INET))
    if filters.start:
        query = query.where(AuditEvent.occurred_at >= filters.start)
    if filters.end:
        query = query.where(AuditEvent.occurred_at < filters.end)
    return query


def page(
    db: Session, filters: AuditFilters, page_number: int, page_size: int
) -> tuple[list[tuple[AuditEvent, str | None]], int]:
    query = filtered(db, filters)
    total = db.scalar(select(func.count()).select_from(query.order_by(None).subquery())) or 0
    rows = db.execute(
        query.order_by(AuditEvent.id.desc()).limit(page_size).offset((page_number - 1) * page_size)
    ).all()
    return [(event, username) for event, username in rows], total


def count(db: Session, filters: AuditFilters) -> int:
    query = filtered(db, filters).order_by(None)
    return db.scalar(select(func.count()).select_from(query.subquery())) or 0


def iterate(
    db: Session, filters: AuditFilters, batch_size: int = 1000
) -> Iterator[tuple[AuditEvent, str | None]]:
    """Newest first, in keyset-paginated batches (no large OFFSET)."""
    last_id: int | None = None
    while True:
        query = filtered(db, filters)
        if last_id is not None:
            query = query.where(AuditEvent.id < last_id)
        rows = db.execute(query.order_by(AuditEvent.id.desc()).limit(batch_size)).all()
        if not rows:
            return
        yield from ((event, username) for event, username in rows)
        last_id = rows[-1][0].id


def distinct_actions(db: Session) -> list[str]:
    return list(db.scalars(select(AuditEvent.action).distinct().order_by(AuditEvent.action)).all())
