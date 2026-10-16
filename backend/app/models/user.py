"""Users and groups. Personal data is stored encrypted (see ``core.crypto``)."""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, LargeBinary, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAt, UuidPrimaryKey


class User(UuidPrimaryKey, CreatedAt, Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("global_role IN ('user', 'admin')", name="global_role"),
        CheckConstraint("status IN ('active', 'disabled')", name="status"),
        CheckConstraint("auth_source IN ('local', 'oidc', 'ldap')", name="auth_source"),
        Index("uq_users_username_lower", text("lower(username)"), unique=True),
        Index(
            "uq_users_external_identity",
            "auth_source",
            "external_id",
            unique=True,
            postgresql_where=text("external_id IS NOT NULL"),
        ),
    )

    username: Mapped[str] = mapped_column(String(64))
    email_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    email_bidx: Mapped[bytes | None] = mapped_column(LargeBinary, unique=True)
    display_name_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    dek_wrapped: Mapped[bytes] = mapped_column(LargeBinary)
    key_version: Mapped[int] = mapped_column(default=1)
    password_hash: Mapped[str | None] = mapped_column(String(255))
    password_changed_at: Mapped[datetime | None]
    must_change_password: Mapped[bool] = mapped_column(default=False)
    auth_source: Mapped[str] = mapped_column(String(16), default="local")
    # OIDC ``sub`` or directory entry identifier; stable across renames.
    external_id: Mapped[str | None] = mapped_column(String(255))
    global_role: Mapped[str] = mapped_column(String(16), default="user")
    status: Mapped[str] = mapped_column(String(16), default="active")
    last_login_at: Mapped[datetime | None]
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class Group(UuidPrimaryKey, CreatedAt, Base):
    __tablename__ = "groups"
    __table_args__ = (
        CheckConstraint("source IN ('local', 'oidc', 'ldap')", name="source"),
        Index("uq_groups_name_lower", text("lower(name)"), unique=True),
    )

    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(String(500), default="")
    source: Mapped[str] = mapped_column(String(16), default="local")


class GroupMember(CreatedAt, Base):
    __tablename__ = "group_members"

    group_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True
    )
