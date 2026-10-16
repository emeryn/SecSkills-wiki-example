"""Dormant accounts are disabled; recent ones and the last administrator are kept."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update

from app.core.context import AppContext
from app.models import AuditEvent, User
from app.services import account_hygiene
from tests.helpers import make_user

NOW = datetime(2026, 10, 15, tzinfo=UTC)


def _last_login(ctx: AppContext, username: str, days_ago: int | None) -> None:
    with ctx.sessions() as db:
        moment = NOW - timedelta(days=days_ago) if days_ago is not None else None
        db.execute(update(User).where(User.username == username).values(last_login_at=moment))
        db.execute(
            update(User).where(User.username == username).values(created_at=NOW - timedelta(400))
        )
        db.commit()


def _status(ctx: AppContext) -> dict[str, str]:
    with ctx.sessions() as db:
        return {u.username: u.status for u in db.scalars(select(User)).all()}


def test_dormant_accounts_are_disabled(ctx: AppContext) -> None:
    for name, days in (("recent", 10), ("dormant", 200), ("never", None)):
        make_user(ctx, name)
        _last_login(ctx, name, days)
    with ctx.sessions() as db:
        assert account_hygiene.disable_inactive(db, 180, now=NOW) == 2
        events = db.scalars(
            select(AuditEvent).where(AuditEvent.action == "user.disabled_inactive")
        ).all()
    assert _status(ctx) == {"recent": "active", "dormant": "disabled", "never": "disabled"}
    assert len(events) == 2
    assert all(e.actor_user_id is None and e.user_agent == "system" for e in events)


def test_last_active_administrator_is_kept(ctx: AppContext) -> None:
    make_user(ctx, "old-admin", role="admin")
    make_user(ctx, "older-admin", role="admin")
    _last_login(ctx, "old-admin", 300)
    _last_login(ctx, "older-admin", 400)
    with ctx.sessions() as db:
        assert account_hygiene.disable_inactive(db, 180, now=NOW) == 1
    assert sorted(_status(ctx).values()) == ["active", "disabled"]


def test_zero_days_disables_the_job(ctx: AppContext) -> None:
    make_user(ctx, "dormant")
    _last_login(ctx, "dormant", 1000)
    with ctx.sessions() as db:
        assert account_hygiene.disable_inactive(db, 0, now=NOW) == 0
