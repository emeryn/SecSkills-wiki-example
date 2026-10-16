"""Spaces, memberships, pages (tree), revisions and favorites."""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAt, UuidPrimaryKey

SPACE_ROLES = ("viewer", "editor", "space_admin")


class Space(UuidPrimaryKey, CreatedAt, Base):
    __tablename__ = "spaces"
    __table_args__ = (
        CheckConstraint("visibility IN ('restricted', 'internal')", name="visibility"),
    )

    key: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(String(500), default="")
    visibility: Mapped[str] = mapped_column(String(16), default="restricted")
    home_page_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(
            "pages.id",
            use_alter=True,
            ondelete="SET NULL",
            deferrable=True,
            initially="IMMEDIATE",
        )
    )
    archived_at: Mapped[datetime | None]
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class SpaceMember(CreatedAt, Base):
    """A user or a group with a role in a space (principal_id is not a foreign key)."""

    __tablename__ = "space_members"
    __table_args__ = (
        CheckConstraint("principal_type IN ('user', 'group')", name="principal_type"),
        CheckConstraint("role IN ('viewer', 'editor', 'space_admin')", name="role"),
        Index("ix_space_members_principal", "principal_type", "principal_id"),
    )

    space_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("spaces.id", ondelete="CASCADE"), primary_key=True
    )
    principal_type: Mapped[str] = mapped_column(String(8), primary_key=True)
    principal_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    role: Mapped[str] = mapped_column(String(16))
    source: Mapped[str] = mapped_column(String(8), default="manual")


class Page(UuidPrimaryKey, CreatedAt, Base):
    __tablename__ = "pages"
    __table_args__ = (
        UniqueConstraint("space_id", "slug", name="uq_pages_space_slug"),
        Index(
            "uq_pages_space_title_live",
            "space_id",
            "title_norm",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_pages_space_parent", "space_id", "parent_id", "position"),
        CheckConstraint("depth BETWEEN 1 AND 5", name="depth"),
        Index("ix_pages_search_vector", "search_vector", postgresql_using="gin"),
    )

    space_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("spaces.id", ondelete="CASCADE"))
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("pages.id", ondelete="CASCADE"))
    slug: Mapped[str] = mapped_column(String(80))
    title: Mapped[str] = mapped_column(String(200))
    title_norm: Mapped[str] = mapped_column(String(200))
    current_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(
            "revisions.id",
            use_alter=True,
            ondelete="SET NULL",
            deferrable=True,
            initially="IMMEDIATE",
        )
    )
    position: Mapped[int] = mapped_column(Integer, default=0)
    depth: Mapped[int] = mapped_column(SmallInteger, default=1)
    deleted_at: Mapped[datetime | None] = mapped_column(index=True)
    deleted_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    # Every page trashed with a subtree points to the page the user deleted.
    trash_root_id: Mapped[uuid.UUID | None]
    # Title (weight A) and current body (weight B), maintained on every save; see search_service.
    search_vector: Mapped[str | None] = mapped_column(TSVECTOR)
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class Revision(UuidPrimaryKey, CreatedAt, Base):
    __tablename__ = "revisions"
    __table_args__ = (UniqueConstraint("page_id", "number", name="uq_revisions_page_number"),)

    page_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pages.id", ondelete="CASCADE"))
    number: Mapped[int] = mapped_column(Integer)
    author_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    message: Mapped[str] = mapped_column(String(500), default="")
    restored_from_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("revisions.id", ondelete="SET NULL")
    )


class Favorite(CreatedAt, Base):
    __tablename__ = "favorites"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    page_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pages.id", ondelete="CASCADE"), primary_key=True, index=True
    )


class Attachment(UuidPrimaryKey, CreatedAt, Base):
    """File attached to a page; bytes live in the attachment volume under ``storage_key``."""

    __tablename__ = "attachments"

    page_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pages.id", ondelete="CASCADE"), index=True
    )
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    filename: Mapped[str] = mapped_column(String(200))
    storage_key: Mapped[str] = mapped_column(String(64), unique=True)
    content_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    # Only re-encoded raster images may be displayed inline.
    inline_allowed: Mapped[bool] = mapped_column(default=False)
