"""Trash: a deleted page goes with its subtree, can be restored for 30 days, then is purged."""

import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import Page, Space
from app.repositories import pages as page_repo
from app.services import audit_service
from app.services.audit_service import SYSTEM, Actor

logger = logging.getLogger(__name__)

RETENTION = timedelta(days=30)


def trash_page(db: Session, space: Space, page_id: uuid.UUID, actor: Actor) -> None:
    page = page_repo.get_live(db, space.id, page_id, lock=True)
    if page is None:
        raise AppError(404, "NOT_FOUND", "Not found")
    if page.id == space.home_page_id:
        raise AppError(409, "HOME_PAGE", "The home page of a space cannot be deleted")
    now = datetime.now(UTC)
    moved = 0
    for node in page_repo.subtree(db, page.id):
        if node.deleted_at is None:
            node.deleted_at = now
            node.deleted_by = actor.user_id
            node.trash_root_id = page.id
            moved += 1
    siblings = [p for p in page_repo.children(db, space.id, page.parent_id) if p.id != page.id]
    for index, sibling in enumerate(siblings):
        sibling.position = index
    audit_service.record(
        db,
        actor,
        "page.deleted",
        target_type="page",
        target_id=page.id,
        before={"space": space.key, "title": page.title, "pages": moved},
    )
    db.commit()


def _depth_from(node: Page, by_id: dict[uuid.UUID, Page], root: Page, root_depth: int) -> int:
    depth, current = root_depth, node
    while current.id != root.id and current.parent_id is not None:
        depth += 1
        current = by_id[current.parent_id]
    return depth


def restore(db: Session, space: Space, root_id: uuid.UUID, actor: Actor) -> Page:
    """Restore a trashed subtree; at top level when its parent no longer exists."""
    root = page_repo.get_any(db, space.id, root_id)
    if root is None or root.deleted_at is None or root.trash_root_id != root.id:
        raise AppError(404, "NOT_FOUND", "Not found")
    pages = list(page_repo.trashed_with_root(db, root.id))
    conflicts = [
        p.title for p in pages if page_repo.live_title_owner(db, space.id, p.title_norm) is not None
    ]
    if conflicts:
        raise AppError(
            409, "TITLE_CONFLICT", "Pages with the same titles exist", {"titles": conflicts}
        )
    parent = page_repo.get_live(db, space.id, root.parent_id) if root.parent_id else None
    if parent is None:
        root.parent_id = None
    root_depth = parent.depth + 1 if parent else 1
    by_id = {p.id: p for p in pages}
    depths = {p.id: _depth_from(p, by_id, root, root_depth) for p in pages}
    if max(depths.values()) > 5:  # noqa: PLR2004 - mirrors page_service.MAX_DEPTH
        root.parent_id = None
        depths = {p.id: _depth_from(p, by_id, root, 1) for p in pages}
    root.position = len(page_repo.children(db, space.id, root.parent_id))
    for page in pages:
        page.depth = depths[page.id]
        page.deleted_at = None
        page.deleted_by = None
        page.trash_root_id = None
    audit_service.record(
        db,
        actor,
        "page.restored",
        target_type="page",
        target_id=root.id,
        after={"space": space.key, "title": root.title, "pages": len(pages)},
    )
    db.commit()
    return root


def purge(db: Session, space: Space, root_id: uuid.UUID, actor: Actor) -> None:
    """Delete a trashed subtree permanently (revisions and favorites go with it)."""
    root = page_repo.get_any(db, space.id, root_id)
    if root is None or root.trash_root_id != root.id:
        raise AppError(404, "NOT_FOUND", "Not found")
    audit_service.record(
        db,
        actor,
        "page.purged",
        target_type="page",
        target_id=root.id,
        before={"space": space.key, "title": root.title},
    )
    db.delete(root)
    db.commit()


def purge_expired(db: Session) -> int:
    """Scheduled job: purge subtrees trashed more than 30 days ago."""
    expired = page_repo.expired_trash_roots(db, datetime.now(UTC) - RETENTION)
    for root in expired:
        audit_service.record(
            db,
            SYSTEM,
            "page.purged",
            target_type="page",
            target_id=root.id,
            before={"title": root.title, "reason": "retention"},
        )
        db.delete(root)
    db.commit()
    return len(expired)
