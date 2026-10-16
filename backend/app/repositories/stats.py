"""Aggregate counts for the administration dashboard (no content is read)."""

from datetime import datetime
from typing import Any, Literal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import (
    Attachment,
    AuditEvent,
    BlockedIp,
    Page,
    Revision,
    ServerError,
    Space,
    User,
)

Bucket = Literal["hour", "day"]


def users(db: Session, since: datetime) -> dict[str, int]:
    row = db.execute(
        select(
            func.count(),
            func.count().filter(User.status == "active"),
            func.count().filter(User.status == "disabled"),
            func.count().filter(User.last_login_at >= since),
        ).select_from(User)
    ).one()
    return {"total": row[0], "active": row[1], "disabled": row[2], "signed_in": row[3]}


def content(db: Session, since: datetime) -> dict[str, int]:
    spaces = db.scalar(select(func.count()).select_from(Space).where(Space.archived_at.is_(None)))
    pages = db.scalar(select(func.count()).select_from(Page).where(Page.deleted_at.is_(None)))
    revisions = db.scalar(
        select(func.count()).select_from(Revision).where(Revision.created_at >= since)
    )
    attachments = db.execute(
        select(func.count(), func.coalesce(func.sum(Attachment.size_bytes), 0)).select_from(
            Attachment
        )
    ).one()
    return {
        "spaces": spaces or 0,
        "pages": pages or 0,
        "revisions": revisions or 0,
        "attachments": attachments[0],
        "attachment_bytes": int(attachments[1]),
    }


def audit_count(db: Session, action: str, since: datetime, outcome: str | None = None) -> int:
    query = (
        select(func.count())
        .select_from(AuditEvent)
        .where(AuditEvent.action == action, AuditEvent.occurred_at >= since)
    )
    if outcome is not None:
        query = query.where(AuditEvent.outcome == outcome)
    return db.scalar(query) or 0


def latest_audit(
    db: Session, action: str, limit: int, since: datetime | None = None
) -> list[tuple[AuditEvent, str | None]]:
    query = (
        select(AuditEvent, User.username)
        .outerjoin(User, User.id == AuditEvent.actor_user_id)
        .where(AuditEvent.action == action)
    )
    if since is not None:
        query = query.where(AuditEvent.occurred_at >= since)
    rows = db.execute(query.order_by(AuditEvent.id.desc()).limit(limit)).all()
    return [(event, username) for event, username in rows]


def blocked_ips(db: Session, now: datetime) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(BlockedIp)
            .where(or_(BlockedIp.expires_at.is_(None), BlockedIp.expires_at > now))
        )
        or 0
    )


def server_errors(db: Session, since: datetime, limit: int) -> tuple[int, list[ServerError]]:
    total = db.scalar(
        select(func.count()).select_from(ServerError).where(ServerError.occurred_at >= since)
    )
    recent = db.scalars(
        select(ServerError)
        .where(ServerError.occurred_at >= since)
        .order_by(ServerError.id.desc())
        .limit(limit)
    ).all()
    return total or 0, list(recent)


def _series(
    db: Session, column: Any, since: datetime, bucket: Bucket, *where: Any
) -> dict[Any, int]:
    slot = func.date_trunc(bucket, func.timezone("UTC", column)).label("slot")
    rows = db.execute(
        select(slot, func.count()).where(column >= since, *where).group_by(slot)
    ).all()
    return {row[0]: row[1] for row in rows}


def activity(db: Session, since: datetime, bucket: Bucket) -> tuple[dict[Any, int], dict[Any, int]]:
    """Successful sign-ins and saved revisions per UTC hour or day (naive UTC datetimes)."""
    sign_ins = _series(
        db,
        AuditEvent.occurred_at,
        since,
        bucket,
        AuditEvent.action == "auth.login",
        AuditEvent.outcome == "success",
    )
    edits = _series(db, Revision.created_at, since, bucket)
    return sign_ins, edits
