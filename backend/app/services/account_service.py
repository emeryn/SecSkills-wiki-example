"""Self-service account operations: password, enrollment completion, sessions, password reset."""

import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.core.context import AppContext
from app.core.errors import AppError
from app.core.security import new_token, token_hash
from app.models import AuthSession, PasswordResetToken, User
from app.repositories import reset_tokens, throttle
from app.repositories import sessions as session_repo
from app.repositories import users as user_repo
from app.services import audit_service, auth_service, mfa_service, session_service
from app.services.audit_service import Actor
from app.services.password_policy import password_problems
from app.services.session_service import Principal
from app.services.user_profile import email_index, read_profile

logger = logging.getLogger(__name__)

RESET_TTL = timedelta(minutes=30)
INVITE_TTL = timedelta(hours=72)
RESET_IP_FREE_ATTEMPTS = 10


def ensure_password_allowed(password: str, username: str) -> None:
    problems = password_problems(password, username)
    if problems:
        raise AppError(
            422, "PASSWORD_REJECTED", "Password does not meet the policy: " + ", ".join(problems)
        )


def _set_password(ctx: AppContext, user: User, password: str) -> None:
    ensure_password_allowed(password, user.username)
    user.password_hash = ctx.hasher.hash(password)
    user.password_changed_at = datetime.now(UTC)
    user.must_change_password = False


def advance(db: Session, ctx: AppContext, session: AuthSession, user: User, actor: Actor) -> str:
    """Recompute the session state after a step (password change, enrollment); rotates the id."""
    previous = session.state
    state = session_service.compute_state(
        user,
        has_mfa=mfa_service.has_mfa(db, user.id),
        mfa_verified=session.mfa_verified_at is not None,
    )
    token = session_service.transition(ctx, session, user, state)
    if previous != "active" and state == "active":
        auth_service.complete_sign_in(db, ctx, session, user, actor)
    return token


def change_password(
    db: Session, ctx: AppContext, principal: Principal, current: str, new: str, actor: Actor
) -> str:
    """Change the password, revoke every other session and rotate this one."""
    user, session = principal.user, principal.session
    if user.auth_source != "local":
        raise AppError(409, "NOT_LOCAL_ACCOUNT", "This account's password is managed elsewhere")
    if not ctx.hasher.verify(user.password_hash, current):
        audit_service.record(
            db,
            actor,
            "account.password_change",
            outcome="failure",
            target_type="user",
            target_id=user.id,
        )
        db.commit()
        raise AppError(400, "INVALID_CURRENT_PASSWORD", "Current password is incorrect")
    if current == new:
        raise AppError(
            422, "PASSWORD_REJECTED", "Password does not meet the policy: SAME_AS_CURRENT"
        )
    _set_password(ctx, user, new)
    now = datetime.now(UTC)
    session_repo.revoke_all(db, user.id, now, except_id=session.id)
    session.reauth_at = now
    audit_service.record(
        db, actor, "account.password_change", target_type="user", target_id=user.id
    )
    token = advance(db, ctx, session, user, actor)
    db.commit()
    return token


def mfa_enrolled(
    db: Session, ctx: AppContext, principal: Principal, method: str, actor: Actor
) -> str:
    """After adding a factor: the session counts as MFA-verified and moves on."""
    session = principal.session
    now = datetime.now(UTC)
    session.mfa_verified_at = now
    session.reauth_at = now
    audit_service.record(
        db,
        actor,
        "account.mfa_added",
        target_type="user",
        target_id=principal.user.id,
        after={"method": method},
    )
    token = advance(db, ctx, session, principal.user, actor)
    db.commit()
    return token


def list_sessions(db: Session, principal: Principal) -> list[AuthSession]:
    return session_repo.list_active_for_user(db, principal.user.id, datetime.now(UTC))


def revoke_session(db: Session, principal: Principal, session_id: uuid.UUID, actor: Actor) -> None:
    target = session_repo.get_for_user(db, principal.user.id, session_id)
    if target is None or target.revoked_at is not None:
        raise AppError(404, "NOT_FOUND", "Not found")
    target.revoked_at = datetime.now(UTC)
    audit_service.record(
        db, actor, "account.session_revoked", target_type="session", target_id=session_id
    )
    db.commit()


def revoke_other_sessions(db: Session, principal: Principal, actor: Actor) -> int:
    count = session_repo.revoke_all(
        db, principal.user.id, datetime.now(UTC), except_id=principal.session.id
    )
    audit_service.record(
        db,
        actor,
        "account.sessions_revoked",
        target_type="user",
        target_id=principal.user.id,
        after={"count": count},
    )
    db.commit()
    return count


# --- Password reset -----------------------------------------------------------------------------


def issue_reset_token(
    db: Session, ctx: AppContext, user: User, purpose: str
) -> tuple[str, datetime]:
    """Invalidate older tokens and return ``(link, expires_at)`` for a new single-use token."""
    now = datetime.now(UTC)
    reset_tokens.invalidate_for_user(db, user.id, now)
    token = new_token()
    expires_at = now + (INVITE_TTL if purpose == "invite" else RESET_TTL)
    db.add(
        PasswordResetToken(
            user_id=user.id, token_hash=token_hash(token), purpose=purpose, expires_at=expires_at
        )
    )
    return f"{ctx.settings.public_origin}/reset-password?token={token}", expires_at


def request_reset(db: Session, ctx: AppContext, email: str, actor: Actor) -> tuple[str, str] | None:
    """Create a reset token when the address belongs to an active local account.

    Returns ``(email, link)`` to send outside the request; the HTTP response is identical
    whatever the outcome.
    """
    ip_subject = f"reset:{actor.ip}"
    if throttle.retry_after(db, [ip_subject], datetime.now(UTC)) > 0:
        return None
    throttle.register_failure(db, ip_subject, RESET_IP_FREE_ATTEMPTS, datetime.now(UTC))
    user = user_repo.find_by_email_index(db, email_index(ctx.cipher, email))
    result = None
    if (
        user is not None
        and user.status == "active"
        and user.auth_source == "local"
        and ctx.mailer.enabled
    ):
        link, _ = issue_reset_token(db, ctx, user, "reset")
        address = read_profile(ctx.cipher, user).email
        if address:
            result = (address, link)
        audit_service.record(
            db, actor, "auth.password_reset_requested", target_type="user", target_id=user.id
        )
    db.commit()
    return result


def send_reset_email(ctx: AppContext, address: str, link: str) -> None:
    try:
        ctx.mailer.send(
            address,
            "Reset your wiki password",
            f"Open this link within 30 minutes to choose a new password:\n\n{link}\n\n"
            "If you did not ask for this, ignore this message.",
        )
    except OSError:
        logger.warning("Password reset email could not be sent")


def confirm_reset(
    db: Session, ctx: AppContext, token: str, new_password: str, actor: Actor
) -> None:
    """Set a new password from a reset or invitation link; every session is revoked."""
    now = datetime.now(UTC)
    row = reset_tokens.find_usable(db, token_hash(token), now)
    user = user_repo.get(db, row.user_id) if row is not None else None
    if row is None or user is None or user.status != "active":
        audit_service.record(db, actor, "auth.password_reset", outcome="failure")
        db.commit()
        raise AppError(400, "INVALID_TOKEN", "This link is invalid or has expired")
    _set_password(ctx, user, new_password)
    row.used_at = now
    session_repo.revoke_all(db, user.id, now)
    audit_service.record(
        db,
        actor,
        "auth.password_reset",
        target_type="user",
        target_id=user.id,
        after={"purpose": row.purpose},
    )
    db.commit()
