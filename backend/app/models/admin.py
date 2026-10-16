"""Administration state: encrypted settings, blocked client IPs and recorded server errors."""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, LargeBinary, SmallInteger, String
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Setting(Base):
    """One settings section (``syslog``, ``smtp``…) as JSON encrypted under its own data key."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(32), primary_key=True)
    value_enc: Mapped[bytes] = mapped_column(LargeBinary)
    dek_wrapped: Mapped[bytes] = mapped_column(LargeBinary)
    key_version: Mapped[int] = mapped_column(default=1)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    updated_at: Mapped[datetime]


class BlockedIp(Base):
    """Client IP blocked after a honeytoken hit; ``expires_at`` null means until unblocked."""

    __tablename__ = "blocked_ips"

    ip: Mapped[str] = mapped_column(INET, primary_key=True)
    reason: Mapped[str] = mapped_column(String(200))
    hits: Mapped[int] = mapped_column(default=1)
    blocked_at: Mapped[datetime]
    expires_at: Mapped[datetime | None]


class ServerError(Base):
    """A 5xx response or a failed scheduled job, shown on the admin dashboard (no details)."""

    __tablename__ = "server_errors"
    __table_args__ = (CheckConstraint("source IN ('request', 'job')", name="source"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    occurred_at: Mapped[datetime] = mapped_column(index=True)
    source: Mapped[str] = mapped_column(String(16))
    method: Mapped[str] = mapped_column(String(16))
    path: Mapped[str] = mapped_column(String(300))
    status: Mapped[int] = mapped_column(SmallInteger)
    request_id: Mapped[str | None] = mapped_column(String(64))
