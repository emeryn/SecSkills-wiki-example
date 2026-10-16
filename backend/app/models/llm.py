"""Ask the wiki: page chunks with embeddings, versioned system prompts, daily token usage."""

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import BigInteger, ForeignKey, SmallInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import UserDefinedType

from app.models.base import Base, CreatedAt, UuidPrimaryKey


class Vector(UserDefinedType[Any]):
    """pgvector column of any dimension (the embedding model decides).

    Values are written and compared through ``repositories.chunks`` with an explicit
    ``CAST(:value AS vector)``: the driver sends text, never an untyped parameter.
    """

    cache_ok = True

    def get_col_spec(self, **_: Any) -> str:
        return "vector"


class PageChunk(UuidPrimaryKey, CreatedAt, Base):
    """A piece of a page's current revision, with the space it belongs to for filtering."""

    __tablename__ = "page_chunks"

    page_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pages.id", ondelete="CASCADE"), index=True
    )
    space_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("spaces.id", ondelete="CASCADE"), index=True
    )
    revision_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("revisions.id", ondelete="CASCADE"))
    ordinal: Mapped[int] = mapped_column(SmallInteger)
    content: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(String(200))
    embedding: Mapped[Any] = mapped_column(Vector())


class LlmPrompt(Base):
    """One version of a system prompt; the newest row of a name is the one in use."""

    __tablename__ = "llm_prompts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(32), index=True)
    content: Mapped[str] = mapped_column(Text)
    is_default: Mapped[bool] = mapped_column(default=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime]


class LlmUsage(Base):
    """Requests and tokens per user and day, for the daily quota."""

    __tablename__ = "llm_usage"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    day: Mapped[date] = mapped_column(primary_key=True)
    requests: Mapped[int] = mapped_column(default=0)
    prompt_tokens: Mapped[int] = mapped_column(default=0)
    completion_tokens: Mapped[int] = mapped_column(default=0)
