"""Page chunks and similarity search, always restricted to the spaces the user can read."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import Float, String, bindparam, cast, delete, exists, select, text
from sqlalchemy.orm import Session

from app.models import Page, PageChunk, Space
from app.models.llm import Vector
from app.repositories.spaces import readable_space_ids


def vector_literal(values: Sequence[float]) -> str:
    return "[" + ",".join(repr(float(v)) for v in values) + "]"


def pages_needing_index(db: Session, model: str, limit: int) -> list[Page]:
    """Live pages whose current revision has no chunks for ``model`` yet."""
    indexed = exists().where(
        PageChunk.page_id == Page.id,
        PageChunk.revision_id == Page.current_revision_id,
        PageChunk.model == model,
    )
    return list(
        db.scalars(
            select(Page)
            .where(Page.deleted_at.is_(None), Page.current_revision_id.is_not(None), ~indexed)
            .order_by(Page.updated_at)
            .limit(limit)
        ).all()
    )


def replace_page_chunks(
    db: Session,
    page: Page,
    revision_id: uuid.UUID,
    model: str,
    items: list[tuple[str, list[float]]],
) -> None:
    db.execute(delete(PageChunk).where(PageChunk.page_id == page.id))
    statement = text(
        "INSERT INTO page_chunks (id, page_id, space_id, revision_id, ordinal, content, model, "
        "embedding) VALUES (:id, :page_id, :space_id, :revision_id, :ordinal, :content, :model, "
        "CAST(:embedding AS vector))"
    )
    for ordinal, (content, embedding) in enumerate(items):
        db.execute(
            statement,
            {
                "id": uuid.uuid4(),
                "page_id": page.id,
                "space_id": page.space_id,
                "revision_id": revision_id,
                "ordinal": ordinal,
                "content": content,
                "model": model,
                "embedding": vector_literal(embedding),
            },
        )


@dataclass(frozen=True)
class Match:
    content: str
    page_id: uuid.UUID
    title: str
    slug: str
    space_key: str
    similarity: float


def search(
    db: Session,
    user_id: uuid.UUID,
    embedding: list[float],
    model: str,
    limit: int,
    min_similarity: float,
) -> list[Match]:
    """Nearest chunks among readable, live pages: the permission filter is inside the query."""
    query_vector = cast(
        bindparam("query_vector", vector_literal(embedding), type_=String), Vector()
    )
    distance = PageChunk.embedding.op("<=>", return_type=Float)(query_vector)
    statement = (
        select(
            PageChunk.content,
            Page.id,
            Page.title,
            Page.slug,
            Space.key,
            (1 - distance).label("similarity"),
        )
        .join(Page, Page.id == PageChunk.page_id)
        .join(Space, Space.id == PageChunk.space_id)
        .where(
            PageChunk.space_id.in_(readable_space_ids(user_id)),
            Page.space_id == PageChunk.space_id,
            Page.deleted_at.is_(None),
            PageChunk.revision_id == Page.current_revision_id,
            PageChunk.model == model,
            distance <= 1 - min_similarity,
        )
        .order_by(distance)
        .limit(limit)
    )
    rows = db.execute(statement).all()
    return [
        Match(
            content=row[0],
            page_id=row[1],
            title=row[2],
            slug=row[3],
            space_key=row[4],
            similarity=float(row[5]),
        )
        for row in rows
    ]
