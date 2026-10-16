"""Second factors: TOTP, WebAuthn credentials and recovery codes."""

import uuid
from collections.abc import Sequence

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models import RecoveryCode, TotpCredential, WebAuthnCredential


def get_totp(db: Session, user_id: uuid.UUID) -> TotpCredential | None:
    return db.get(TotpCredential, user_id)


def webauthn_credentials(db: Session, user_id: uuid.UUID) -> Sequence[WebAuthnCredential]:
    return db.scalars(
        select(WebAuthnCredential)
        .where(WebAuthnCredential.user_id == user_id)
        .order_by(WebAuthnCredential.created_at)
    ).all()


def find_webauthn(
    db: Session, user_id: uuid.UUID, credential_id: bytes
) -> WebAuthnCredential | None:
    return db.scalar(
        select(WebAuthnCredential).where(
            WebAuthnCredential.user_id == user_id, WebAuthnCredential.credential_id == credential_id
        )
    )


def get_webauthn(db: Session, user_id: uuid.UUID, row_id: uuid.UUID) -> WebAuthnCredential | None:
    return db.scalar(
        select(WebAuthnCredential).where(
            WebAuthnCredential.user_id == user_id, WebAuthnCredential.id == row_id
        )
    )


def unused_recovery_codes(db: Session, user_id: uuid.UUID) -> Sequence[RecoveryCode]:
    return db.scalars(
        select(RecoveryCode).where(RecoveryCode.user_id == user_id, RecoveryCode.used_at.is_(None))
    ).all()


def count_unused_recovery_codes(db: Session, user_id: uuid.UUID) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(RecoveryCode)
            .where(RecoveryCode.user_id == user_id, RecoveryCode.used_at.is_(None))
        )
        or 0
    )


def delete_recovery_codes(db: Session, user_id: uuid.UUID) -> None:
    db.execute(delete(RecoveryCode).where(RecoveryCode.user_id == user_id))


def delete_all_factors(db: Session, user_id: uuid.UUID) -> None:
    db.execute(delete(TotpCredential).where(TotpCredential.user_id == user_id))
    db.execute(delete(WebAuthnCredential).where(WebAuthnCredential.user_id == user_id))
    delete_recovery_codes(db, user_id)
