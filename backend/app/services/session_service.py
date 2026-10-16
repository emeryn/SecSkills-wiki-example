"""Session lifecycle: creation, rotation, state transitions, lookup with sliding idle expiry."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.context import AppContext
from app.core.permissions import ROLE_PERMISSIONS, Permission
from app.core.security import csrf_token, new_token, token_hash
from app.models import AuthSession, User
from app.repositories import sessions as session_repo
from app.services.audit_service import Actor

TOUCH_INTERVAL = timedelta(seconds=60)


@dataclass(frozen=True)
class Principal:
    """The signed-in user as seen by authorization checks."""

    session: AuthSession
    user: User

    @property
    def permissions(self) -> frozenset[Permission]:
        # Admin rights require a second factor verified in this very session.
        if self.user.global_role == "admin" and self.session.mfa_verified_at is None:
            return ROLE_PERMISSIONS["user"]
        return ROLE_PERMISSIONS.get(self.user.global_role, frozenset())

    @property
    def is_admin(self) -> bool:
        return Permission.USERS_MANAGE in self.permissions


def compute_state(user: User, *, has_mfa: bool, mfa_verified: bool) -> str:
    """Next session step: second factor, then forced password change, then MFA enrollment."""
    if has_mfa and not mfa_verified:
        return "mfa_required"
    if user.must_change_password:
        return "password_change_required"
    if user.global_role == "admin" and not has_mfa:
        return "mfa_enrollment_required"
    return "active"


def _lifetimes(settings: Settings, user: User, state: str) -> tuple[timedelta, timedelta]:
    if state != "active":
        pending = timedelta(minutes=settings.pending_session_minutes)
        return pending, pending
    if user.global_role == "admin":
        return (
            timedelta(minutes=settings.admin_session_idle_minutes),
            timedelta(hours=settings.admin_session_absolute_hours),
        )
    return (
        timedelta(minutes=settings.session_idle_minutes),
        timedelta(hours=settings.session_absolute_hours),
    )


def create(
    db: Session, ctx: AppContext, user: User, state: str, actor: Actor
) -> tuple[str, AuthSession]:
    now = datetime.now(UTC)
    idle, absolute = _lifetimes(ctx.settings, user, state)
    token = new_token()
    session = AuthSession(
        token_hash=token_hash(token),
        user_id=user.id,
        state=state,
        ip=actor.ip,
        user_agent=actor.user_agent[:512],
        last_seen_at=now,
        idle_expires_at=now + idle,
        absolute_expires_at=now + absolute,
    )
    db.add(session)
    db.flush()
    return token, session


def transition(ctx: AppContext, session: AuthSession, user: User, state: str) -> str:
    """Move to ``state`` with a new session id (rotation at every privilege change)."""
    now = datetime.now(UTC)
    idle, absolute = _lifetimes(ctx.settings, user, state)
    if session.state != "active" and state == "active":
        session.absolute_expires_at = now + absolute
    else:
        session.absolute_expires_at = min(session.absolute_expires_at, now + absolute)
    session.state = state
    session.idle_expires_at = min(now + idle, session.absolute_expires_at)
    session.last_seen_at = now
    session.webauthn_challenge = None
    token = new_token()
    session.token_hash = token_hash(token)
    return token


def resolve(db: Session, ctx: AppContext, token: str) -> Principal | None:
    """Session and user for a cookie; slides the idle expiry at most once a minute."""
    now = datetime.now(UTC)
    session = session_repo.find_valid(db, token_hash(token), now)
    if session is None:
        return None
    user = db.get(User, session.user_id)
    if user is None or user.status != "active":
        return None
    if now - session.last_seen_at >= TOUCH_INTERVAL:
        idle, _ = _lifetimes(ctx.settings, user, session.state)
        session.last_seen_at = now
        session.idle_expires_at = min(now + idle, session.absolute_expires_at)
        db.commit()
    return Principal(session=session, user=user)


def csrf_for(ctx: AppContext, session: AuthSession) -> str:
    return csrf_token(ctx.csrf_key, session.token_hash)


def recently_authenticated(ctx: AppContext, session: AuthSession) -> bool:
    if session.reauth_at is None:
        return False
    return datetime.now(UTC) - session.reauth_at <= timedelta(
        minutes=ctx.settings.reauth_window_minutes
    )
