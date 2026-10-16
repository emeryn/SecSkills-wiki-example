"""Pages, revisions, favorites and the recent-changes feed. Pages are always read within a space."""

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import Row, func, select
from sqlalchemy.orm import Session

from app.models import Attachment, Favorite, Page, Revision, Space, User
from app.repositories.spaces import readable_space_ids


def live_pages(db: Session, space_id: uuid.UUID) -> Sequence[Page]:
    return db.scalars(
        select(Page)
        .where(Page.space_id == space_id, Page.deleted_at.is_(None))
        .order_by(Page.depth, Page.position, func.lower(Page.title))
    ).all()


def get_live(
    db: Session, space_id: uuid.UUID, page_id: uuid.UUID, *, lock: bool = False
) -> Page | None:
    query = select(Page).where(
        Page.id == page_id, Page.space_id == space_id, Page.deleted_at.is_(None)
    )
    return db.scalar(query.with_for_update() if lock else query)


def get_live_by_slug(db: Session, space_id: uuid.UUID, slug: str) -> Page | None:
    return db.scalar(
        select(Page).where(Page.space_id == space_id, Page.slug == slug, Page.deleted_at.is_(None))
    )


def get_any(db: Session, space_id: uuid.UUID, page_id: uuid.UUID) -> Page | None:
    return db.scalar(select(Page).where(Page.id == page_id, Page.space_id == space_id))


def slug_taken(db: Session, space_id: uuid.UUID, slug: str) -> bool:
    return (
        db.scalar(select(Page.id).where(Page.space_id == space_id, Page.slug == slug)) is not None
    )


def live_title_owner(db: Session, space_id: uuid.UUID, title_norm: str) -> uuid.UUID | None:
    return db.scalar(
        select(Page.id).where(
            Page.space_id == space_id, Page.title_norm == title_norm, Page.deleted_at.is_(None)
        )
    )


def children(db: Session, space_id: uuid.UUID, parent_id: uuid.UUID | None) -> Sequence[Page]:
    parent = Page.parent_id.is_(None) if parent_id is None else Page.parent_id == parent_id
    return db.scalars(
        select(Page)
        .where(Page.space_id == space_id, parent, Page.deleted_at.is_(None))
        .order_by(Page.position, func.lower(Page.title))
    ).all()


def subtree(db: Session, root_id: uuid.UUID) -> Sequence[Page]:
    """The page and all its descendants (recursive CTE), whatever their trash state."""
    tree = select(Page.id).where(Page.id == root_id).cte("tree", recursive=True)
    tree = tree.union_all(select(Page.id).join(tree, Page.parent_id == tree.c.id))
    return db.scalars(select(Page).where(Page.id.in_(select(tree.c.id)))).all()


def trash_roots(db: Session, space_id: uuid.UUID) -> Sequence[Page]:
    return db.scalars(
        select(Page)
        .where(
            Page.space_id == space_id, Page.deleted_at.is_not(None), Page.trash_root_id == Page.id
        )
        .order_by(Page.deleted_at.desc())
    ).all()


def trashed_with_root(db: Session, root_id: uuid.UUID) -> Sequence[Page]:
    return db.scalars(select(Page).where(Page.trash_root_id == root_id)).all()


def expired_trash_roots(db: Session, before: datetime) -> Sequence[Page]:
    return db.scalars(
        select(Page).where(Page.trash_root_id == Page.id, Page.deleted_at < before)
    ).all()


def max_revision_number(db: Session, page_id: uuid.UUID) -> int:
    return db.scalar(select(func.max(Revision.number)).where(Revision.page_id == page_id)) or 0


def get_revision(db: Session, page_id: uuid.UUID, revision_id: uuid.UUID) -> Revision | None:
    return db.scalar(
        select(Revision).where(Revision.id == revision_id, Revision.page_id == page_id)
    )


def revisions(
    db: Session, page_id: uuid.UUID, page: int, page_size: int
) -> tuple[Sequence[Row[Revision, str | None]], int]:
    total = (
        db.scalar(select(func.count()).select_from(Revision).where(Revision.page_id == page_id))
        or 0
    )
    rows = db.execute(
        select(Revision, User.username)
        .outerjoin(User, User.id == Revision.author_id)
        .where(Revision.page_id == page_id)
        .order_by(Revision.number.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return rows, total


def author_name(db: Session, user_id: uuid.UUID | None) -> str | None:
    return db.scalar(select(User.username).where(User.id == user_id)) if user_id else None


def recent_changes(
    db: Session, user_id: uuid.UUID, space_id: uuid.UUID | None, limit: int
) -> Sequence[Row[Revision, Page, Space, str | None]]:
    """Latest revisions of live pages in spaces the user can read (filtered in SQL)."""
    query = (
        select(Revision, Page, Space, User.username)
        .join(Page, Page.id == Revision.page_id)
        .join(Space, Space.id == Page.space_id)
        .outerjoin(User, User.id == Revision.author_id)
        .where(Page.deleted_at.is_(None), Space.id.in_(readable_space_ids(user_id)))
        .order_by(Revision.created_at.desc())
        .limit(limit)
    )
    if space_id is not None:
        query = query.where(Space.id == space_id)
    return db.execute(query).all()


def favorites(db: Session, user_id: uuid.UUID) -> Sequence[Row[Page, Space]]:
    """Starred pages the user can still read; others are hidden, not revealed."""
    return db.execute(
        select(Page, Space)
        .join(Favorite, Favorite.page_id == Page.id)
        .join(Space, Space.id == Page.space_id)
        .where(
            Favorite.user_id == user_id,
            Page.deleted_at.is_(None),
            Space.id.in_(readable_space_ids(user_id)),
        )
        .order_by(func.lower(Page.title))
    ).all()


def get_favorite(db: Session, user_id: uuid.UUID, page_id: uuid.UUID) -> Favorite | None:
    return db.get(Favorite, (user_id, page_id))


def readable_live_page(db: Session, user_id: uuid.UUID, page_id: uuid.UUID) -> Page | None:
    return db.scalar(
        select(Page).where(
            Page.id == page_id,
            Page.deleted_at.is_(None),
            Page.space_id.in_(readable_space_ids(user_id)),
        )
    )


def attachments(db: Session, page_id: uuid.UUID) -> Sequence[Attachment]:
    return db.scalars(
        select(Attachment).where(Attachment.page_id == page_id).order_by(Attachment.created_at)
    ).all()


def space_of(db: Session, page: Page) -> Space | None:
    return db.get(Space, page.space_id)
