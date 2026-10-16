"""Stored responses of state-changing requests, keyed by user and ``Idempotency-Key``."""

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, LargeBinary, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAt


class IdempotencyKey(CreatedAt, Base):
    __tablename__ = "idempotency_keys"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    key: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    request_hash: Mapped[bytes] = mapped_column(LargeBinary)
    status_code: Mapped[int | None] = mapped_column(SmallInteger)
    content_type: Mapped[str | None] = mapped_column(String(100))
    response_body: Mapped[bytes | None] = mapped_column(LargeBinary)
    expires_at: Mapped[datetime] = mapped_column(index=True)
