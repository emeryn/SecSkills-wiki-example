"""User administration. Admins create accounts; users activate them through an invitation link."""

import uuid
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.context import AppContext
from app.core.crypto import normalize
from app.core.errors import AppError
from app.models import User
from app.repositories import mfa as mfa_repo
from app.repositories import sessions as session_repo
from app.repositories import users as user_repo
from app.services import account_service, audit_service
from app.services.audit_service import Actor
from app.services.session_service import Principal
from app.services.user_profile import email_index, new_user, read_profile, set_profile


def get_user(db: Session, user_id: uuid.UUID) -> User:
    user = user_repo.get(db, user_id)
    if user is None:
        raise AppError(404, "NOT_FOUND", "Not found")
    return user


def _snapshot(ctx: AppContext, user: User) -> dict[str, object]:
    profile = read_profile(ctx.cipher, user)
    return {
        "username": user.username,
        "email": profile.email,
        "display_name": profile.display_name,
        "role": user.global_role,
        "status": user.status,
    }


def create_user(
    db: Session,
    ctx: AppContext,
    *,
    username: str,
    email: str | None,
    display_name: str | None,
    role: str,
    actor: Actor,
) -> tuple[User, str, datetime]:
    """Create an account without a password; returns the invitation link to set one."""
    decoys = {normalize(name) for name in ctx.runtime.snapshot().security.decoy_usernames}
    if normalize(username) in decoys:
        raise AppError(409, "USERNAME_RESERVED", "This username is reserved")
    if user_repo.find_by_username(db, username) is not None:
        raise AppError(409, "USERNAME_TAKEN", "This username is already used")
    if email and user_repo.find_by_email_index(db, email_index(ctx.cipher, email)) is not None:
        raise AppError(409, "EMAIL_TAKEN", "This email address is already used")
    user = new_user(ctx.cipher, username, role=role)
    set_profile(ctx.cipher, user, email=email, display_name=display_name)
    db.add(user)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise AppError(409, "USER_EXISTS", "This user already exists") from exc
    link, expires_at = account_service.issue_reset_token(db, ctx, user, "invite")
    audit_service.record(
        db, actor, "user.created", target_type="user", target_id=user.id, after=_snapshot(ctx, user)
    )
    db.commit()
    return user, link, expires_at


def _guard_last_admin(
    db: Session, user: User, *, new_role: str | None, new_status: str | None
) -> None:
    losing_admin = (
        user.global_role == "admin"
        and user.status == "active"
        and (
            (new_role is not None and new_role != "admin")
            or (new_status is not None and new_status != "active")
        )
    )
    if losing_admin and user_repo.count_active_admins(db) <= 1:
        raise AppError(409, "LAST_ADMIN", "At least one active administrator is required")


def update_user(
    db: Session,
    ctx: AppContext,
    principal: Principal,
    user: User,
    *,
    changes: dict[str, object],
    actor: Actor,
) -> User:
    """Apply profile, role and status changes; role or status changes revoke the sessions."""
    if user.id == principal.user.id and ({"role", "status"} & changes.keys()):
        raise AppError(409, "SELF_CHANGE", "You cannot change your own role or status")
    before = _snapshot(ctx, user)
    new_role = changes.get("role")
    new_status = changes.get("status")
    _guard_last_admin(
        db,
        user,
        new_role=str(new_role) if new_role is not None else None,
        new_status=str(new_status) if new_status is not None else None,
    )
    if "email" in changes or "display_name" in changes:
        profile = read_profile(ctx.cipher, user)
        email = changes.get("email", profile.email)
        if email and email != profile.email:
            other = user_repo.find_by_email_index(db, email_index(ctx.cipher, str(email)))
            if other is not None and other.id != user.id:
                raise AppError(409, "EMAIL_TAKEN", "This email address is already used")
        set_profile(
            ctx.cipher,
            user,
            email=str(email) if email else None,
            display_name=str(changes.get("display_name", profile.display_name) or "") or None,
        )
    privileges_changed = False
    if new_role is not None and new_role != user.global_role and user.auth_source != "local":
        # The admin groups decide, at each sign-in: a manual change would be overwritten.
        raise AppError(
            409, "ROLE_MANAGED_BY_SSO", "The role of a single sign-on account comes from its groups"
        )
    if new_role is not None and new_role != user.global_role:
        user.global_role = str(new_role)
        privileges_changed = True
    if new_status is not None and new_status != user.status:
        user.status = str(new_status)
        privileges_changed = True
    if privileges_changed:
        session_repo.revoke_all(db, user.id, datetime.now(UTC))
    audit_service.record(
        db,
        actor,
        "user.updated",
        target_type="user",
        target_id=user.id,
        before=before,
        after=_snapshot(ctx, user),
    )
    db.commit()
    return user


def reset_link(db: Session, ctx: AppContext, user: User, actor: Actor) -> tuple[str, datetime]:
    if user.status != "active" or user.auth_source != "local":
        raise AppError(
            409, "NOT_LOCAL_ACTIVE", "Only active local accounts can reset their password"
        )
    link, expires_at = account_service.issue_reset_token(db, ctx, user, "reset")
    audit_service.record(
        db, actor, "user.reset_link_created", target_type="user", target_id=user.id
    )
    db.commit()
    return link, expires_at


def revoke_sessions(db: Session, user: User, actor: Actor) -> int:
    count = session_repo.revoke_all(db, user.id, datetime.now(UTC))
    audit_service.record(
        db,
        actor,
        "user.sessions_revoked",
        target_type="user",
        target_id=user.id,
        after={"count": count},
    )
    db.commit()
    return count


def reset_mfa(db: Session, principal: Principal, user: User, actor: Actor) -> None:
    """Remove every second factor; the user must enroll again (admins at their next sign-in)."""
    if user.id == principal.user.id:
        raise AppError(409, "SELF_CHANGE", "Use your account page to manage your own factors")
    mfa_repo.delete_all_factors(db, user.id)
    session_repo.revoke_all(db, user.id, datetime.now(UTC))
    audit_service.record(db, actor, "user.mfa_reset", target_type="user", target_id=user.id)
    db.commit()
