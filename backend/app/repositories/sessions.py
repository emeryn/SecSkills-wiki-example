"""Server-side sessions."""

import uuid
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import AuthSession


def find_valid(db: Session, token_hash: bytes, now: datetime) -> AuthSession | None:
    """Session matching the cookie, not revoked and within both idle and absolute expiry."""
    return db.scalar(
        select(AuthSession).where(
            AuthSession.token_hash == token_hash,
            AuthSession.revoked_at.is_(None),
            AuthSession.idle_expires_at > now,
            AuthSession.absolute_expires_at > now,
        )
    )


def list_active_for_user(db: Session, user_id: uuid.UUID, now: datetime) -> list[AuthSession]:
    return list(
        db.scalars(
            select(AuthSession)
            .where(
                AuthSession.user_id == user_id,
                AuthSession.revoked_at.is_(None),
                AuthSession.idle_expires_at > now,
                AuthSession.absolute_expires_at > now,
            )
            .order_by(AuthSession.last_seen_at.desc())
        )
    )


def get_for_user(db: Session, user_id: uuid.UUID, session_id: uuid.UUID) -> AuthSession | None:
    return db.scalar(
        select(AuthSession).where(AuthSession.id == session_id, AuthSession.user_id == user_id)
    )


def revoke_all(
    db: Session, user_id: uuid.UUID, now: datetime, *, except_id: uuid.UUID | None = None
) -> int:
    statement = update(AuthSession).where(
        AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None)
    )
    if except_id is not None:
        statement = statement.where(AuthSession.id != except_id)
    result = db.execute(statement.values(revoked_at=now))
    return int(getattr(result, "rowcount", 0) or 0)
