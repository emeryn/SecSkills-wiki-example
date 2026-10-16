"""Sessions, second factors, reset tokens and sign-in throttling."""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, LargeBinary, String
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAt, UuidPrimaryKey

SESSION_STATES = ("active", "mfa_required", "password_change_required", "mfa_enrollment_required")


class AuthSession(UuidPrimaryKey, CreatedAt, Base):
    __tablename__ = "sessions"
    __table_args__ = (
        CheckConstraint(
            "state IN ('active', 'mfa_required', 'password_change_required', "
            "'mfa_enrollment_required')",
            name="state",
        ),
    )

    token_hash: Mapped[bytes] = mapped_column(LargeBinary, unique=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    state: Mapped[str] = mapped_column(String(32))
    ip: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str] = mapped_column(String(512), default="")
    last_seen_at: Mapped[datetime]
    idle_expires_at: Mapped[datetime]
    absolute_expires_at: Mapped[datetime]
    mfa_verified_at: Mapped[datetime | None]
    reauth_at: Mapped[datetime | None]
    revoked_at: Mapped[datetime | None]
    webauthn_challenge: Mapped[bytes | None] = mapped_column(LargeBinary)
    webauthn_challenge_expires_at: Mapped[datetime | None]


class TotpCredential(CreatedAt, Base):
    __tablename__ = "totp_credentials"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    secret_enc: Mapped[bytes] = mapped_column(LargeBinary)
    last_used_step: Mapped[int] = mapped_column(BigInteger, default=0)
    confirmed_at: Mapped[datetime | None]


class WebAuthnCredential(UuidPrimaryKey, CreatedAt, Base):
    __tablename__ = "webauthn_credentials"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    credential_id: Mapped[bytes] = mapped_column(LargeBinary, unique=True)
    public_key: Mapped[bytes] = mapped_column(LargeBinary)
    sign_count: Mapped[int] = mapped_column(BigInteger, default=0)
    name: Mapped[str] = mapped_column(String(64))
    last_used_at: Mapped[datetime | None]


class RecoveryCode(UuidPrimaryKey, Base):
    __tablename__ = "recovery_codes"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    code_hash: Mapped[bytes] = mapped_column(LargeBinary)
    used_at: Mapped[datetime | None]


class PasswordResetToken(UuidPrimaryKey, CreatedAt, Base):
    __tablename__ = "password_reset_tokens"
    __table_args__ = (CheckConstraint("purpose IN ('reset', 'invite')", name="purpose"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[bytes] = mapped_column(LargeBinary, unique=True)
    purpose: Mapped[str] = mapped_column(String(16))
    expires_at: Mapped[datetime]
    used_at: Mapped[datetime | None]


class KnownDevice(UuidPrimaryKey, CreatedAt, Base):
    __tablename__ = "known_devices"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    fingerprint_hash: Mapped[bytes] = mapped_column(LargeBinary)
    last_seen_at: Mapped[datetime]


class AuthThrottle(Base):
    """Failure counters per account and per IP; drives progressive delays, not lockout."""

    __tablename__ = "auth_throttle"

    subject: Mapped[str] = mapped_column(String(160), primary_key=True)
    failures: Mapped[int] = mapped_column(default=0)
    last_failure_at: Mapped[datetime]
    next_allowed_at: Mapped[datetime | None]


class OidcFlow(Base):
    """An OIDC authorization request in progress (10 minutes, single use).

    ``state_hash`` identifies it; ``binding_hash`` ties it to the browser that started it (a
    cookie), so a callback URL replayed into another browser is refused.
    """

    __tablename__ = "oidc_flows"
    __table_args__ = (CheckConstraint("purpose IN ('login', 'reauth')", name="purpose"),)

    state_hash: Mapped[bytes] = mapped_column(LargeBinary, primary_key=True)
    binding_hash: Mapped[bytes] = mapped_column(LargeBinary)
    nonce: Mapped[str] = mapped_column(String(64))
    code_verifier: Mapped[str] = mapped_column(String(128))
    purpose: Mapped[str] = mapped_column(String(16))
    next_path: Mapped[str] = mapped_column(String(500))
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE")
    )
    expires_at: Mapped[datetime] = mapped_column(index=True)
