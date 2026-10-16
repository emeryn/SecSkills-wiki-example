"""API keys for MCP clients.

A key is ``wk_<prefix>_<secret>``: 32 random bytes of secret, shown once. Only its SHA-256 is
stored (keys are long random values: a slow hash adds nothing), looked up through a unique index.
Keys always expire (365 days at most, 30 for admin-scoped keys), can be revoked, and stop working
as soon as the account is disabled. Their rights never exceed the owner's: scopes only narrow them.
"""

import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.security import token_hash
from app.models import ApiKey, User
from app.services import audit_service
from app.services.audit_service import Actor

PREFIX = "wk_"
SCOPES = ("pages:read", "pages:write", "admin")
MAX_DAYS = 365
MAX_ADMIN_DAYS = 30
MAX_KEYS_PER_USER = 20
TOUCH_INTERVAL = timedelta(minutes=1)


@dataclass(frozen=True)
class Issued:
    key: ApiKey
    secret: str


def issue(
    db: Session, user: User, actor: Actor, *, name: str, scopes: list[str], days: int
) -> Issued:
    if not scopes or any(scope not in SCOPES for scope in scopes):
        raise AppError(422, "INVALID_SCOPES", "Unknown scope")
    if "admin" in scopes:
        if user.global_role != "admin":
            raise AppError(403, "FORBIDDEN", "Only administrators can create admin keys")
        days = min(days, MAX_ADMIN_DAYS)
    active = [k for k in list_for(db, user.id) if status(k) == "active"]
    if len(active) >= MAX_KEYS_PER_USER:
        raise AppError(409, "TOO_MANY_KEYS", f"At most {MAX_KEYS_PER_USER} active keys")
    public = secrets.token_hex(4)
    secret = f"{PREFIX}{public}_{secrets.token_urlsafe(32)}"
    key = ApiKey(
        id=uuid.uuid4(),
        user_id=user.id,
        name=name.strip(),
        prefix=f"{PREFIX}{public}",
        key_hash=token_hash(secret),
        scopes=sorted(set(scopes)),
        expires_at=datetime.now(UTC) + timedelta(days=min(days, MAX_DAYS)),
    )
    db.add(key)
    db.flush()
    audit_service.record(
        db,
        actor,
        "api_key.created",
        severity="warning" if "admin" in scopes else "info",
        target_type="api_key",
        target_id=key.id,
        after={
            "name": key.name,
            "prefix": key.prefix,
            "scopes": key.scopes,
            "expires_at": key.expires_at.isoformat(),
        },
    )
    db.commit()
    return Issued(key, secret)


def list_for(db: Session, user_id: uuid.UUID) -> list[ApiKey]:
    return list(
        db.scalars(
            select(ApiKey).where(ApiKey.user_id == user_id).order_by(ApiKey.created_at.desc())
        ).all()
    )


def status(key: ApiKey, now: datetime | None = None) -> str:
    if key.revoked_at is not None:
        return "revoked"
    if key.expires_at <= (now or datetime.now(UTC)):
        return "expired"
    return "active"


def revoke(db: Session, user_id: uuid.UUID, key_id: uuid.UUID, actor: Actor) -> None:
    key = db.get(ApiKey, key_id)
    # Another user's key does not exist for the caller.
    if key is None or key.user_id != user_id:
        raise AppError(404, "NOT_FOUND", "Not found")
    if key.revoked_at is None:
        key.revoked_at = datetime.now(UTC)
        audit_service.record(
            db,
            actor,
            "api_key.revoked",
            target_type="api_key",
            target_id=key.id,
            before={"prefix": key.prefix},
        )
    db.commit()


def authenticate(db: Session, secret: str, ip: str | None) -> tuple[ApiKey, User] | None:
    """Key and owner for a presented secret, or None (unknown, revoked, expired, owner disabled)."""
    if not secret.startswith(PREFIX) or len(secret) > 200:  # noqa: PLR2004
        return None
    key = db.scalar(select(ApiKey).where(ApiKey.key_hash == token_hash(secret)))
    now = datetime.now(UTC)
    if key is None or status(key, now) != "active":
        return None
    user = db.get(User, key.user_id)
    if user is None or user.status != "active":
        return None
    if key.last_used_at is None or now - key.last_used_at >= TOUCH_INTERVAL:
        key.last_used_at = now
        key.last_used_ip = ip
        db.commit()
    return key, user
