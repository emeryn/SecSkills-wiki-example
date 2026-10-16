"""Sign-in (local, directory, OIDC), second factor, step-up re-authentication and sign-out."""

import hashlib
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy.orm import Session

from app.core.context import AppContext
from app.core.crypto import normalize
from app.core.errors import AppError
from app.models import AuthSession, KnownDevice, User
from app.repositories import throttle
from app.repositories import users as user_repo
from app.services import (
    audit_service,
    honeytoken_service,
    ldap_service,
    mfa_service,
    session_service,
    sso_config,
    sso_provisioning,
)
from app.services.audit_service import Actor
from app.services.ldap_service import DirectoryUnavailableError
from app.services.sso_provisioning import Identity, SsoError
from app.services.user_profile import read_profile

logger = logging.getLogger(__name__)

ACCOUNT_FREE_ATTEMPTS = 5
IP_FREE_ATTEMPTS = 20
MFA_FREE_ATTEMPTS = 5

SecondFactor = Literal["totp", "webauthn", "recovery_code"]


@dataclass(frozen=True)
class SignInResult:
    token: str
    session: AuthSession
    user: User


def _throttled(db: Session, subjects: list[str]) -> None:
    wait = throttle.retry_after(db, subjects, datetime.now(UTC))
    if wait > 0:
        raise AppError(429, "RATE_LIMITED", f"Too many attempts. Try again in {wait} seconds")


def login(db: Session, ctx: AppContext, username: str, password: str, actor: Actor) -> SignInResult:
    """Same response and comparable timing whether the account exists or not."""
    if honeytoken_service.is_decoy(db, ctx, username):
        ctx.hasher.verify(None, password)
        honeytoken_service.trigger(db, ctx, actor, "decoy_login", {"username": username[:64]})
        db.commit()
        raise AppError(401, "INVALID_CREDENTIALS", "Invalid username or password")
    account_subject = f"account:{normalize(username)}"
    ip_subject = f"ip:{actor.ip}"
    _throttled(db, [account_subject, ip_subject])

    user = user_repo.find_by_username(db, username)
    user, reason = _check_password(db, ctx, user, username, password, actor)
    if reason is None and user is not None:
        reason = _local_sign_in_policy(db, ctx, user, actor)
    now = datetime.now(UTC)
    if reason is not None or user is None:
        throttle.register_failure(db, account_subject, ACCOUNT_FREE_ATTEMPTS, now)
        throttle.register_failure(db, ip_subject, IP_FREE_ATTEMPTS, now)
        audit_service.record(
            db,
            actor,
            "auth.login",
            outcome="failure",
            target_type="user" if user else None,
            target_id=user.id if user else None,
            after={"reason": reason} if reason != "invalid_credentials" else None,
        )
        db.commit()
        raise AppError(401, "INVALID_CREDENTIALS", "Invalid username or password")

    if user.password_hash and ctx.hasher.needs_rehash(user.password_hash):
        user.password_hash = ctx.hasher.hash(password)
    throttle.clear(db, account_subject)
    return _open_session(db, ctx, user, actor, now)


def _check_password(
    db: Session, ctx: AppContext, user: User | None, username: str, password: str, actor: Actor
) -> tuple[User | None, str | None]:
    """``(user, None)`` when the password is right, else ``(user or None, failure reason)``.

    Local accounts are checked locally; unknown usernames and directory accounts against the
    directory when it is enabled; OIDC accounts never accept a password.
    """
    if user is not None and user.auth_source == "local":
        usable = user.status == "active"
        verified = ctx.hasher.verify(user.password_hash if usable else None, password)
        return user, None if verified else "invalid_credentials"
    directory = sso_config.ldap(ctx)
    if (user is not None and user.auth_source != "ldap") or not directory.enabled:
        ctx.hasher.verify(None, password)
        return user, "sso_account" if user is not None else "invalid_credentials"
    try:
        found = ldap_service.authenticate(
            directory, sso_config.allowed_networks(ctx, "ldap"), username, password
        )
    except DirectoryUnavailableError as exc:
        logger.error("Directory unavailable for sign-in", extra={"error": str(exc)})
        raise AppError(503, "DIRECTORY_UNAVAILABLE", "Sign-in is temporarily unavailable") from exc
    if found is None:
        return user, "invalid_credentials"
    identity = Identity(
        source="ldap",
        external_id=found.external_id,
        username=found.username,
        email=found.email,
        display_name=found.display_name,
        groups=found.groups,
    )
    try:
        signed_in = sso_provisioning.sign_in_user(
            db,
            ctx,
            identity,
            auto_provision=directory.auto_provision,
            mapping=directory.group_mapping,
            actor=actor,
            admin_groups=directory.admin_groups,
        )
    except SsoError as exc:
        return user, exc.reason
    return signed_in, None


def _local_sign_in_policy(db: Session, ctx: AppContext, user: User, actor: Actor) -> str | None:
    """With "admins only", local passwords are break-glass access for administrators."""
    if user.auth_source != "local":
        return None
    if ctx.runtime.snapshot().security.local_sign_in == "all":
        return None
    if user.global_role != "admin":
        return "local_sign_in_disabled"
    audit_service.record(
        db,
        actor,
        "auth.break_glass",
        severity="critical",
        target_type="user",
        target_id=user.id,
    )
    return None


def _open_session(
    db: Session, ctx: AppContext, user: User, actor: Actor, now: datetime
) -> SignInResult:
    has_mfa = mfa_service.has_mfa(db, user.id)
    state = session_service.compute_state(user, has_mfa=has_mfa, mfa_verified=False)
    token, session = session_service.create(db, ctx, user, state, actor)
    session.reauth_at = now
    if state == "active":
        complete_sign_in(db, ctx, session, user, actor)
    else:
        audit_service.record(
            db, actor, "auth.password_verified", target_type="user", target_id=user.id
        )
    db.commit()
    return SignInResult(token, session, user)


def verify_second_factor(
    db: Session,
    ctx: AppContext,
    principal: session_service.Principal,
    method: SecondFactor,
    payload: str | dict[str, Any],
    actor: Actor,
) -> str:
    """Complete the MFA step of sign-in; returns the rotated session token."""
    session, user = principal.session, principal.user
    subject = f"mfa:{user.id}"
    _throttled(db, [subject])
    if not _check_factor(db, ctx, session, user, method, payload):
        throttle.register_failure(db, subject, MFA_FREE_ATTEMPTS, datetime.now(UTC))
        audit_service.record(
            db,
            actor,
            "auth.mfa",
            outcome="failure",
            target_type="user",
            target_id=user.id,
            after={"method": method},
        )
        db.commit()
        raise AppError(401, "INVALID_CODE", "Verification failed")
    throttle.clear(db, subject)
    now = datetime.now(UTC)
    session.mfa_verified_at = now
    session.reauth_at = now
    state = session_service.compute_state(user, has_mfa=True, mfa_verified=True)
    token = session_service.transition(ctx, session, user, state)
    if state == "active":
        complete_sign_in(db, ctx, session, user, actor, method=method)
    db.commit()
    return token


def _check_factor(
    db: Session,
    ctx: AppContext,
    session: AuthSession,
    user: User,
    method: SecondFactor,
    payload: str | dict[str, Any],
) -> bool:
    if method == "totp" and isinstance(payload, str):
        return mfa_service.verify_totp(db, ctx, user, payload)
    if method == "recovery_code" and isinstance(payload, str):
        return mfa_service.use_recovery_code(db, user, payload)
    if method == "webauthn" and isinstance(payload, dict):
        return mfa_service.verify_assertion(db, ctx, session, user, payload)
    return False


def complete_sign_in(
    db: Session,
    ctx: AppContext,
    session: AuthSession,
    user: User,
    actor: Actor,
    method: str | None = None,
) -> None:
    """Record a session becoming active: last sign-in, audit, new-device check for admins."""
    user.last_login_at = datetime.now(UTC)
    audit_service.record(
        db,
        actor,
        "auth.login",
        target_type="user",
        target_id=user.id,
        after={
            "session_id": str(session.id),
            "second_factor": method,
            "source": user.auth_source,
        },
    )
    if user.global_role == "admin":
        _check_known_device(db, ctx, user, actor)


def _check_known_device(db: Session, ctx: AppContext, user: User, actor: Actor) -> None:
    """Admins signing in from an unknown device/network are notified (MFA was already required)."""
    network = ".".join((actor.ip or "").split(".")[:3])
    fingerprint = hashlib.sha256(f"{actor.user_agent}\x00{network}".encode()).digest()
    now = datetime.now(UTC)
    known = db.query(KnownDevice).filter_by(user_id=user.id, fingerprint_hash=fingerprint).first()
    if known is not None:
        known.last_seen_at = now
        return
    db.add(KnownDevice(user_id=user.id, fingerprint_hash=fingerprint, last_seen_at=now))
    audit_service.record(
        db,
        actor,
        "auth.new_device",
        target_type="user",
        target_id=user.id,
        after={"ip": actor.ip, "user_agent": actor.user_agent[:200]},
    )
    email = read_profile(ctx.cipher, user).email
    if email and ctx.mailer.enabled:
        try:
            ctx.mailer.send(
                email,
                "New sign-in to the wiki",
                f"Your administrator account {user.username} signed in from a new device "
                f"({actor.ip}, {actor.user_agent[:120]}).\nIf this was not you, contact an "
                "administrator immediately.",
            )
        except OSError:
            logger.warning("New sign-in notification could not be sent")


def sso_login(db: Session, ctx: AppContext, user: User, actor: Actor) -> SignInResult:
    """Session for a user the identity provider just authenticated (OIDC callback)."""
    return _open_session(db, ctx, user, actor, datetime.now(UTC))


def sso_reauthenticated(
    db: Session, ctx: AppContext, principal: session_service.Principal, actor: Actor
) -> str:
    """The IdP confirmed the identity again (fresh ``auth_time``); returns the rotated token."""
    session, user = principal.session, principal.user
    session.reauth_at = datetime.now(UTC)
    token = session_service.transition(ctx, session, user, session.state)
    audit_service.record(
        db, actor, "auth.reauth", target_type="user", target_id=user.id, after={"via": "oidc"}
    )
    db.commit()
    return token


def _password_matches(db: Session, ctx: AppContext, user: User, password: str) -> bool:
    if user.auth_source == "local":
        return ctx.hasher.verify(user.password_hash, password)
    try:
        found = ldap_service.authenticate(
            sso_config.ldap(ctx), sso_config.allowed_networks(ctx, "ldap"), user.username, password
        )
    except DirectoryUnavailableError as exc:
        raise AppError(
            503, "DIRECTORY_UNAVAILABLE", "Confirmation is temporarily unavailable"
        ) from exc
    return found is not None and found.external_id == user.external_id


def reauthenticate(
    db: Session,
    ctx: AppContext,
    principal: session_service.Principal,
    password: str,
    second_factor: tuple[SecondFactor, str | dict[str, Any]] | None,
    actor: Actor,
) -> str:
    """Step-up authentication before a sensitive action; returns the rotated session token."""
    session, user = principal.session, principal.user
    if user.auth_source == "oidc":
        raise AppError(409, "REAUTH_WITH_SSO", "Confirm your identity with single sign-on")
    subject = f"reauth:{user.id}"
    _throttled(db, [subject])
    ok = _password_matches(db, ctx, user, password)
    if ok and mfa_service.has_mfa(db, user.id):
        ok = second_factor is not None and _check_factor(db, ctx, session, user, *second_factor)
    if not ok:
        throttle.register_failure(db, subject, MFA_FREE_ATTEMPTS, datetime.now(UTC))
        audit_service.record(
            db, actor, "auth.reauth", outcome="failure", target_type="user", target_id=user.id
        )
        db.commit()
        raise AppError(401, "INVALID_CREDENTIALS", "Verification failed")
    throttle.clear(db, subject)
    session.reauth_at = datetime.now(UTC)
    token = session_service.transition(ctx, session, user, session.state)
    audit_service.record(db, actor, "auth.reauth", target_type="user", target_id=user.id)
    db.commit()
    return token


def logout(db: Session, principal: session_service.Principal, actor: Actor) -> None:
    principal.session.revoked_at = datetime.now(UTC)
    audit_service.record(db, actor, "auth.logout", target_type="user", target_id=principal.user.id)
    db.commit()
