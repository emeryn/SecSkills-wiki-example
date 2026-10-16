"""Second factors: TOTP (replay-protected), WebAuthn/passkeys and single-use recovery codes."""

import hashlib
import hmac
import json
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pyotp
import segno
from sqlalchemy.orm import Session
from webauthn import (
    base64url_to_bytes,
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers.exceptions import InvalidAuthenticationResponse, InvalidRegistrationResponse
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from app.core.context import AppContext
from app.core.errors import AppError
from app.models import AuthSession, RecoveryCode, TotpCredential, User, WebAuthnCredential
from app.repositories import mfa as mfa_repo

TOTP_INTERVAL = 30
TOTP_ISSUER = "Wiki"
RECOVERY_CODE_COUNT = 10
CHALLENGE_TTL = timedelta(minutes=5)
_RECOVERY_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"


@dataclass(frozen=True)
class TotpSetup:
    secret: str
    otpauth_uri: str
    qr_png_data_uri: str


@dataclass(frozen=True)
class MfaStatus:
    totp: bool
    webauthn: list[WebAuthnCredential]
    recovery_codes_left: int

    @property
    def enrolled(self) -> bool:
        return self.totp or bool(self.webauthn)


def status(db: Session, user_id: uuid.UUID) -> MfaStatus:
    totp = mfa_repo.get_totp(db, user_id)
    return MfaStatus(
        totp=totp is not None and totp.confirmed_at is not None,
        webauthn=list(mfa_repo.webauthn_credentials(db, user_id)),
        recovery_codes_left=mfa_repo.count_unused_recovery_codes(db, user_id),
    )


def has_mfa(db: Session, user_id: uuid.UUID) -> bool:
    return status(db, user_id).enrolled


# --- TOTP -------------------------------------------------------------------------------------


def _secret(ctx: AppContext, user: User, credential: TotpCredential) -> str:
    dek = ctx.cipher.unwrap(user.dek_wrapped)
    return ctx.cipher.decrypt(dek, credential.secret_enc, f"totp_credentials.secret:{user.id}")


def _matching_step(secret: str, code: str, last_used_step: int) -> int | None:
    """Accept the current step ±1, never a step at or before the last one used (replay)."""
    if not (len(code) == 6 and code.isdigit()):  # noqa: PLR2004
        return None
    totp = pyotp.TOTP(secret, interval=TOTP_INTERVAL)
    current = int(datetime.now(UTC).timestamp()) // TOTP_INTERVAL
    for step in (current - 1, current, current + 1):
        if step > last_used_step and hmac.compare_digest(totp.at(step * TOTP_INTERVAL), code):
            return step
    return None


def start_totp_setup(db: Session, ctx: AppContext, user: User) -> TotpSetup:
    existing = mfa_repo.get_totp(db, user.id)
    if existing is not None and existing.confirmed_at is not None:
        raise AppError(409, "TOTP_ALREADY_ENROLLED", "An authenticator app is already enrolled")
    secret = pyotp.random_base32(32)
    dek = ctx.cipher.unwrap(user.dek_wrapped)
    encrypted = ctx.cipher.encrypt(dek, secret, f"totp_credentials.secret:{user.id}")
    if existing is None:
        db.add(TotpCredential(user_id=user.id, secret_enc=encrypted, last_used_step=0))
    else:
        existing.secret_enc = encrypted
        existing.last_used_step = 0
    uri = pyotp.TOTP(secret, interval=TOTP_INTERVAL).provisioning_uri(
        name=user.username, issuer_name=TOTP_ISSUER
    )
    return TotpSetup(secret, uri, segno.make(uri, error="m").png_data_uri(scale=5))


def confirm_totp(db: Session, ctx: AppContext, user: User, code: str) -> list[str]:
    """Confirm enrollment with a first code; returns new recovery codes when there were none."""
    credential = mfa_repo.get_totp(db, user.id)
    if credential is None or credential.confirmed_at is not None:
        raise AppError(409, "NO_PENDING_TOTP", "Start the authenticator setup first")
    step = _matching_step(_secret(ctx, user, credential), code, credential.last_used_step)
    if step is None:
        raise AppError(400, "INVALID_CODE", "Invalid code")
    credential.last_used_step = step
    credential.confirmed_at = datetime.now(UTC)
    if mfa_repo.count_unused_recovery_codes(db, user.id) == 0:
        return regenerate_recovery_codes(db, user)
    return []


def verify_totp(db: Session, ctx: AppContext, user: User, code: str) -> bool:
    credential = mfa_repo.get_totp(db, user.id)
    if credential is None or credential.confirmed_at is None:
        return False
    step = _matching_step(_secret(ctx, user, credential), code.strip(), credential.last_used_step)
    if step is None:
        return False
    credential.last_used_step = step
    return True


# --- Recovery codes ---------------------------------------------------------------------------


def _code_hash(code: str) -> bytes:
    return hashlib.sha256(code.replace("-", "").strip().lower().encode()).digest()


def regenerate_recovery_codes(db: Session, user: User) -> list[str]:
    mfa_repo.delete_recovery_codes(db, user.id)
    codes = []
    for _ in range(RECOVERY_CODE_COUNT):
        raw = "".join(secrets.choice(_RECOVERY_ALPHABET) for _ in range(10))
        codes.append(f"{raw[:5]}-{raw[5:]}")
        db.add(RecoveryCode(user_id=user.id, code_hash=_code_hash(raw)))
    return codes


def use_recovery_code(db: Session, user: User, code: str) -> bool:
    digest = _code_hash(code)
    for row in mfa_repo.unused_recovery_codes(db, user.id):
        if hmac.compare_digest(row.code_hash, digest):
            row.used_at = datetime.now(UTC)
            return True
    return False


# --- WebAuthn ---------------------------------------------------------------------------------


def _store_challenge(session: AuthSession, challenge: bytes) -> None:
    session.webauthn_challenge = challenge
    session.webauthn_challenge_expires_at = datetime.now(UTC) + CHALLENGE_TTL


def _take_challenge(session: AuthSession) -> bytes:
    challenge, expires = session.webauthn_challenge, session.webauthn_challenge_expires_at
    session.webauthn_challenge = None
    session.webauthn_challenge_expires_at = None
    if challenge is None or expires is None or expires < datetime.now(UTC):
        raise AppError(400, "CHALLENGE_EXPIRED", "Request a new challenge")
    return challenge


def registration_options(
    db: Session, ctx: AppContext, session: AuthSession, user: User
) -> dict[str, Any]:
    options = generate_registration_options(
        rp_id=ctx.settings.public_hostname,
        rp_name="Wiki",
        user_name=user.username,
        user_id=user.id.bytes,
        exclude_credentials=[
            PublicKeyCredentialDescriptor(id=c.credential_id)
            for c in mfa_repo.webauthn_credentials(db, user.id)
        ],
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.PREFERRED,
        ),
    )
    _store_challenge(session, options.challenge)
    return dict(json.loads(options_to_json(options)))


def register_credential(
    db: Session,
    ctx: AppContext,
    session: AuthSession,
    user: User,
    name: str,
    credential: dict[str, Any],
) -> WebAuthnCredential:
    challenge = _take_challenge(session)
    try:
        verified = verify_registration_response(
            credential=credential,
            expected_challenge=challenge,
            expected_rp_id=ctx.settings.public_hostname,
            expected_origin=ctx.settings.public_origin,
        )
    except (InvalidRegistrationResponse, ValueError, KeyError, TypeError) as exc:
        raise AppError(400, "INVALID_CREDENTIAL", "The security key response was rejected") from exc
    row = WebAuthnCredential(
        user_id=user.id,
        credential_id=verified.credential_id,
        public_key=verified.credential_public_key,
        sign_count=verified.sign_count,
        name=name,
    )
    db.add(row)
    return row


def authentication_options(
    db: Session, ctx: AppContext, session: AuthSession, user: User
) -> dict[str, Any]:
    credentials = mfa_repo.webauthn_credentials(db, user.id)
    if not credentials:
        raise AppError(409, "NO_SECURITY_KEY", "No security key is registered")
    options = generate_authentication_options(
        rp_id=ctx.settings.public_hostname,
        allow_credentials=[PublicKeyCredentialDescriptor(id=c.credential_id) for c in credentials],
        user_verification=UserVerificationRequirement.PREFERRED,
    )
    _store_challenge(session, options.challenge)
    return dict(json.loads(options_to_json(options)))


def verify_assertion(
    db: Session, ctx: AppContext, session: AuthSession, user: User, credential: dict[str, Any]
) -> bool:
    challenge = _take_challenge(session)
    try:
        row = mfa_repo.find_webauthn(
            db, user.id, base64url_to_bytes(str(credential.get("rawId", "")))
        )
        if row is None:
            return False
        verified = verify_authentication_response(
            credential=credential,
            expected_challenge=challenge,
            expected_rp_id=ctx.settings.public_hostname,
            expected_origin=ctx.settings.public_origin,
            credential_public_key=row.public_key,
            credential_current_sign_count=row.sign_count,
        )
    except InvalidAuthenticationResponse, ValueError, KeyError, TypeError:
        return False
    row.sign_count = verified.new_sign_count
    row.last_used_at = datetime.now(UTC)
    return True


# --- Removal ----------------------------------------------------------------------------------


def _ensure_not_last_factor(
    db: Session, user: User, *, removing_totp: bool, removing_keys: int
) -> None:
    current = status(db, user.id)
    remaining = (0 if removing_totp else int(current.totp)) + len(current.webauthn) - removing_keys
    if remaining <= 0:
        if user.global_role == "admin":
            raise AppError(
                409, "LAST_FACTOR", "Administrators must keep at least one second factor"
            )
        mfa_repo.delete_recovery_codes(db, user.id)


def remove_totp(db: Session, user: User) -> None:
    credential = mfa_repo.get_totp(db, user.id)
    if credential is None:
        raise AppError(404, "NOT_FOUND", "Not found")
    _ensure_not_last_factor(db, user, removing_totp=True, removing_keys=0)
    db.delete(credential)


def remove_webauthn(db: Session, user: User, row_id: uuid.UUID) -> WebAuthnCredential:
    row = mfa_repo.get_webauthn(db, user.id, row_id)
    if row is None:
        raise AppError(404, "NOT_FOUND", "Not found")
    _ensure_not_last_factor(db, user, removing_totp=False, removing_keys=1)
    db.delete(row)
    return row
