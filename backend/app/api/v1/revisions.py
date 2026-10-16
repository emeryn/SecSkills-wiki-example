"""Revision history of a page: list, read, diff, restore."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response

from app.api.deps import CurrentActor, Db
from app.api.space_access import CurrentSpace, space_editor, space_viewer
from app.api.v1.pages import PageId, live_page, page_out
from app.core.errors import AppError
from app.models import Revision
from app.repositories import pages as page_repo
from app.schemas.common import Page as PageOf
from app.schemas.common import PageParams
from app.schemas.content import DiffLineOut, DiffOut, PageOut, RevisionDetail, RevisionOut
from app.services import revision_service

router = APIRouter(prefix="/spaces/{space}/pages/{page_id}/revisions", tags=["revisions"])


def _out(revision: Revision, author: str | None) -> RevisionOut:
    return RevisionOut(
        id=revision.id,
        number=revision.number,
        title=revision.title,
        message=revision.message,
        author=author,
        created_at=revision.created_at,
        restored_from_id=revision.restored_from_id,
    )


@router.get("", dependencies=[Depends(space_viewer)])
def list_revisions(
    page_id: PageId, params: Annotated[PageParams, Query()], current: CurrentSpace, db: Db
) -> PageOf[RevisionOut]:
    page = live_page(db, current, page_id)
    rows, total = page_repo.revisions(db, page.id, params.page, params.page_size)
    return PageOf(
        items=[_out(r, a) for r, a in rows],
        total=total,
        page=params.page,
        page_size=params.page_size,
    )


@router.get("/{revision_id}", dependencies=[Depends(space_viewer)])
def get_revision(
    page_id: PageId, revision_id: uuid.UUID, current: CurrentSpace, db: Db
) -> RevisionDetail:
    revision = revision_service.get_revision(db, live_page(db, current, page_id), revision_id)
    return RevisionDetail(
        **_out(revision, page_repo.author_name(db, revision.author_id)).model_dump(),
        body=revision.body,
    )


@router.get("/{revision_id}/diff", dependencies=[Depends(space_viewer)])
def diff(
    page_id: PageId,
    revision_id: uuid.UUID,
    current: CurrentSpace,
    db: Db,
    against: Annotated[uuid.UUID | None, Query()] = None,
) -> DiffOut:
    """Changes from ``against`` (default: the current revision) to ``revision_id``."""
    page = live_page(db, current, page_id)
    new = revision_service.get_revision(db, page, revision_id)
    base_id = against or page.current_revision_id
    old = revision_service.get_revision(db, page, base_id) if base_id else new
    return DiffOut(
        old=_out(old, page_repo.author_name(db, old.author_id)),
        new=_out(new, page_repo.author_name(db, new.author_id)),
        lines=[DiffLineOut(**line.__dict__) for line in revision_service.diff(old, new)],
    )


@router.post("/{revision_id}/restore", dependencies=[Depends(space_editor)])
def restore(
    page_id: PageId,
    revision_id: uuid.UUID,
    current: CurrentSpace,
    response: Response,
    db: Db,
    actor: CurrentActor,
) -> PageOut:
    page = page_repo.get_live(db, current.space.id, page_id, lock=True)
    if page is None:
        raise AppError(404, "NOT_FOUND", "Not found")
    restored = revision_service.restore(
        db, current.space, page, revision_id, current.principal.user.id, actor
    )
    return page_out(db, current, restored, response)
