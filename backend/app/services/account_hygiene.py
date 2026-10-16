"""Scheduled account hygiene: dormant accounts are disabled (never the last administrator)."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import User
from app.repositories import sessions as session_repo
from app.repositories import users as user_repo
from app.services import audit_service
from app.services.audit_service import SYSTEM


def disable_inactive(db: Session, days: int, now: datetime | None = None) -> int:
    """Disable active accounts without a sign-in (or, never signed in, created) ``days`` ago."""
    if days <= 0:
        return 0
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(days=days)
    last_seen = func.coalesce(User.last_login_at, User.created_at)
    dormant = db.scalars(
        select(User).where(User.status == "active", last_seen < cutoff).order_by(last_seen)
    ).all()
    admins_left = user_repo.count_active_admins(db)
    disabled = 0
    for user in dormant:
        if user.global_role == "admin":
            if admins_left <= 1:
                continue
            admins_left -= 1
        user.status = "disabled"
        session_repo.revoke_all(db, user.id, now)
        audit_service.record(
            db,
            SYSTEM,
            "user.disabled_inactive",
            target_type="user",
            target_id=user.id,
            before={"status": "active", "last_login_at": str(user.last_login_at)},
            after={"status": "disabled", "inactive_days": days},
        )
        disabled += 1
    db.commit()
    return disabled
