"""Progressive delays per account and per IP. Never a hard lockout: that would enable DoS."""

from datetime import datetime, timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import AuthThrottle

MAX_DELAY_SECONDS = 900


def retry_after(db: Session, subjects: list[str], now: datetime) -> int:
    """Seconds the caller must wait before the next attempt (0 when allowed)."""
    rows = db.scalars(select(AuthThrottle).where(AuthThrottle.subject.in_(subjects))).all()
    waits = [
        int((row.next_allowed_at - now).total_seconds()) + 1
        for row in rows
        if row.next_allowed_at is not None and row.next_allowed_at > now
    ]
    return max(waits, default=0)


def register_failure(db: Session, subject: str, free_attempts: int, now: datetime) -> None:
    """Count a failure; beyond ``free_attempts`` the delay doubles up to 15 minutes."""
    statement = insert(AuthThrottle).values(subject=subject, failures=1, last_failure_at=now)
    row = db.execute(
        statement.on_conflict_do_update(
            index_elements=[AuthThrottle.subject],
            set_={"failures": AuthThrottle.failures + 1, "last_failure_at": now},
        ).returning(AuthThrottle.failures)
    ).one()
    failures: int = row[0]
    if failures > free_attempts:
        delay = min(2 ** (failures - free_attempts - 1), MAX_DELAY_SECONDS)
        db.execute(
            update(AuthThrottle)
            .where(AuthThrottle.subject == subject)
            .values(next_allowed_at=now + timedelta(seconds=delay))
        )


def clear(db: Session, subject: str) -> None:
    db.execute(delete(AuthThrottle).where(AuthThrottle.subject == subject))
