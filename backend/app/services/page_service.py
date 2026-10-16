"""Page creation, editing with optimistic locking, and moves within the tree of a space."""

import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.crypto import normalize
from app.core.errors import AppError
from app.models import Page, Revision, Space
from app.repositories import pages as page_repo
from app.services import search_service
from app.services.slug import unique_slug

MAX_DEPTH = 5
SLUG_MAX_LENGTH = 80


@dataclass(frozen=True)
class PageWithRevision:
    page: Page
    revision: Revision
    author: str | None


def ensure_title_free(
    db: Session, space_id: uuid.UUID, title: str, except_id: uuid.UUID | None = None
) -> None:
    owner = page_repo.live_title_owner(db, space_id, normalize(title))
    if owner is not None and owner != except_id:
        raise AppError(409, "TITLE_TAKEN", "A page with this title already exists in this space")


def _not_found() -> AppError:
    return AppError(404, "NOT_FOUND", "Not found")


def load(db: Session, space: Space, page: Page) -> PageWithRevision:
    if page.current_revision_id is None:
        raise _not_found()
    revision = page_repo.get_revision(db, page.id, page.current_revision_id)
    if revision is None:
        raise _not_found()
    return PageWithRevision(page, revision, page_repo.author_name(db, revision.author_id))


def _renumber(siblings: list[Page]) -> None:
    for index, sibling in enumerate(siblings):
        sibling.position = index


def create_page(
    db: Session,
    space: Space,
    author_id: uuid.UUID,
    *,
    title: str,
    body: str,
    message: str = "",
    parent_id: uuid.UUID | None = None,
) -> Page:
    """New page at the end of its siblings, with revision 1."""
    depth = 1
    if parent_id is not None:
        parent = page_repo.get_live(db, space.id, parent_id)
        if parent is None:
            raise _not_found()
        depth = parent.depth + 1
        if depth > MAX_DEPTH:
            raise AppError(422, "MAX_DEPTH", f"Pages can be nested {MAX_DEPTH} levels deep at most")
    title = title.strip()
    ensure_title_free(db, space.id, title)
    page = Page(
        id=uuid.uuid4(),
        space_id=space.id,
        parent_id=parent_id,
        slug=unique_slug(
            title, SLUG_MAX_LENGTH, "page", lambda c: page_repo.slug_taken(db, space.id, c)
        ),
        title=title,
        title_norm=normalize(title),
        position=len(page_repo.children(db, space.id, parent_id)),
        depth=depth,
    )
    db.add(page)
    db.flush()
    revision = Revision(
        id=uuid.uuid4(),
        page_id=page.id,
        number=1,
        author_id=author_id,
        title=title,
        body=body,
        message=message,
    )
    db.add(revision)
    db.flush()
    page.current_revision_id = revision.id
    search_service.refresh_vector(db, page.id)
    return page


def update_page(
    db: Session,
    space: Space,
    author_id: uuid.UUID,
    page_id: uuid.UUID,
    *,
    expected_revision: uuid.UUID,
    title: str,
    body: str,
    message: str,
) -> Page:
    """Save a new revision if ``expected_revision`` is still current, else 412 (lost update)."""
    page = page_repo.get_live(db, space.id, page_id, lock=True)
    if page is None:
        raise _not_found()
    if page.current_revision_id != expected_revision:
        current = load(db, space, page)
        raise AppError(
            412,
            "STALE_REVISION",
            "This page was changed by someone else",
            {
                "current_revision_id": str(current.revision.id),
                "current_number": current.revision.number,
                "author": current.author,
            },
        )
    current = load(db, space, page)
    title = title.strip()
    if title == current.revision.title and body == current.revision.body:
        return page
    if normalize(title) != page.title_norm:
        ensure_title_free(db, space.id, title, except_id=page.id)
    page.title = title
    page.title_norm = normalize(title)
    revision = Revision(
        id=uuid.uuid4(),
        page_id=page.id,
        number=page_repo.max_revision_number(db, page.id) + 1,
        author_id=author_id,
        title=title,
        body=body,
        message=message,
    )
    db.add(revision)
    db.flush()
    page.current_revision_id = revision.id
    search_service.refresh_vector(db, page.id)
    return page


def move_page(
    db: Session, space: Space, page_id: uuid.UUID, *, parent_id: uuid.UUID | None, position: int
) -> Page:
    """Move under ``parent_id`` (None: top level) at ``position`` among the new siblings."""
    page = page_repo.get_live(db, space.id, page_id, lock=True)
    if page is None:
        raise _not_found()
    subtree = [p for p in page_repo.subtree(db, page.id) if p.deleted_at is None]
    new_depth = 1
    if parent_id is not None:
        if parent_id in {p.id for p in subtree}:
            raise AppError(422, "INVALID_MOVE", "A page cannot be moved under itself")
        parent = page_repo.get_live(db, space.id, parent_id)
        if parent is None:
            raise _not_found()
        new_depth = parent.depth + 1
    deepest = max(p.depth for p in subtree) - page.depth
    if new_depth + deepest > MAX_DEPTH:
        raise AppError(422, "MAX_DEPTH", f"Pages can be nested {MAX_DEPTH} levels deep at most")

    old_siblings = [p for p in page_repo.children(db, space.id, page.parent_id) if p.id != page.id]
    _renumber(old_siblings)
    delta = new_depth - page.depth
    for node in subtree:
        node.depth += delta
    page.parent_id = parent_id
    new_siblings = [p for p in page_repo.children(db, space.id, parent_id) if p.id != page.id]
    new_siblings.insert(max(0, min(position, len(new_siblings))), page)
    _renumber(new_siblings)
    return page
