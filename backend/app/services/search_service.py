"""Full-text search (PostgreSQL ``tsvector`` + GIN), filtered by readable spaces in SQL.

The ``simple`` configuration (no stemming) works for pages written in any language. Snippets
are returned as plain-text segments, never as HTML: the client renders highlights itself.
"""

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Function, Select, func, select, text
from sqlalchemy.orm import Session

from app.models import Page, Revision, Space
from app.repositories.spaces import readable_space_ids

CONFIG = "simple"
# Private-use characters mark highlights inside ts_headline output.
HIGHLIGHT_START = ""
HIGHLIGHT_END = ""
HEADLINE_OPTIONS = (
    f"StartSel={HIGHLIGHT_START}, StopSel={HIGHLIGHT_END}, MaxWords=30, MinWords=12, "
    'MaxFragments=2, FragmentDelimiter=" … "'
)


@dataclass(frozen=True)
class Segment:
    text: str
    highlight: bool


@dataclass(frozen=True)
class Hit:
    page: Page
    space: Space
    revision: Revision
    snippet: list[Segment]


def refresh_vector(db: Session, page_id: uuid.UUID) -> None:
    """Recompute the page's search vector from its current revision (title A, body B)."""
    db.execute(
        text(
            """
            UPDATE pages AS p
            SET search_vector =
                setweight(to_tsvector('simple', r.title), 'A')
                || setweight(to_tsvector('simple', r.body), 'B')
            FROM revisions AS r
            WHERE r.id = p.current_revision_id AND p.id = :page_id
            """
        ),
        {"page_id": page_id},
    )


def segments(headline: str) -> list[Segment]:
    """Split ts_headline output on the highlight markers."""
    result: list[Segment] = []
    rest = headline
    while rest:
        start = rest.find(HIGHLIGHT_START)
        if start < 0:
            result.append(Segment(rest, highlight=False))
            break
        if start > 0:
            result.append(Segment(rest[:start], highlight=False))
        end = rest.find(HIGHLIGHT_END, start + 1)
        end = len(rest) if end < 0 else end
        result.append(Segment(rest[start + 1 : end], highlight=True))
        rest = rest[end + 1 :]
    return [s for s in result if s.text]


def _base(
    user_id: uuid.UUID, q: str, space_id: uuid.UUID | None
) -> tuple[Select[Page, Space, Revision], Function[Any]]:
    query = func.websearch_to_tsquery(CONFIG, q)
    statement = (
        select(Page, Space, Revision)
        .join(Space, Space.id == Page.space_id)
        .join(Revision, Revision.id == Page.current_revision_id)
        .where(
            Page.deleted_at.is_(None),
            Page.search_vector.op("@@")(query),
            Space.id.in_(readable_space_ids(user_id)),
        )
    )
    if space_id is not None:
        statement = statement.where(Space.id == space_id)
    return statement, query


def search(
    db: Session, user_id: uuid.UUID, q: str, space_id: uuid.UUID | None, page: int, page_size: int
) -> tuple[list[Hit], int]:
    statement, query = _base(user_id, q, space_id)
    total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    title_match = func.to_tsvector(CONFIG, Page.title).op("@@")(query)
    rows = db.execute(
        statement.add_columns(func.ts_headline(CONFIG, Revision.body, query, HEADLINE_OPTIONS))
        .order_by(title_match.desc(), func.ts_rank(Page.search_vector, query).desc(), Page.title)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    hits = [Hit(p, s, r, segments(headline or "")) for p, s, r, headline in rows]
    return hits, total
