"""API keys: shown once, stored as a SHA-256 hash, scoped, expiring and revocable."""

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, LargeBinary, String
from sqlalchemy.dialects.postgresql import ARRAY, INET
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAt, UuidPrimaryKey


class ApiKey(UuidPrimaryKey, CreatedAt, Base):
    __tablename__ = "api_keys"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(100))
    # Public part of the key, shown in lists so a key can be recognized without revealing it.
    prefix: Mapped[str] = mapped_column(String(16), unique=True)
    key_hash: Mapped[bytes] = mapped_column(LargeBinary, unique=True)
    scopes: Mapped[list[str]] = mapped_column(ARRAY(String(32)))
    expires_at: Mapped[datetime]
    last_used_at: Mapped[datetime | None]
    last_used_ip: Mapped[str | None] = mapped_column(INET)
    revoked_at: Mapped[datetime | None]
