"""Per-space trash: list, restore (editors), purge permanently (space administrators)."""

import uuid

from fastapi import APIRouter, Depends, status

from app.api.deps import CurrentActor, Db
from app.api.space_access import CurrentSpace, space_admin, space_editor
from app.repositories import pages as page_repo
from app.schemas.content import TrashItem, TreeNode
from app.services import trash_service

router = APIRouter(prefix="/spaces/{space}/trash", tags=["trash"])


@router.get("", dependencies=[Depends(space_editor)])
def list_trash(current: CurrentSpace, db: Db) -> list[TrashItem]:
    items = []
    for root in page_repo.trash_roots(db, current.space.id):
        if root.deleted_at is None:
            continue
        items.append(
            TrashItem(
                id=root.id,
                title=root.title,
                deleted_at=root.deleted_at,
                deleted_by=page_repo.author_name(db, root.deleted_by),
                pages=len(page_repo.trashed_with_root(db, root.id)),
                purge_after=root.deleted_at + trash_service.RETENTION,
            )
        )
    return items


@router.post("/{page_id}/restore", dependencies=[Depends(space_editor)])
def restore(page_id: uuid.UUID, current: CurrentSpace, db: Db, actor: CurrentActor) -> TreeNode:
    page = trash_service.restore(db, current.space, page_id, actor)
    return TreeNode(
        id=page.id,
        parent_id=page.parent_id,
        slug=page.slug,
        title=page.title,
        position=page.position,
        depth=page.depth,
    )


@router.delete(
    "/{page_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(space_admin)]
)
def purge(page_id: uuid.UUID, current: CurrentSpace, db: Db, actor: CurrentActor) -> None:
    trash_service.purge(db, current.space, page_id, actor)
