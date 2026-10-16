"""Pages: read, create, edit with optimistic locking (``If-Match``), move, delete to trash."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Path, Response, status

from app.api.deps import CurrentActor, Db
from app.api.space_access import CurrentSpace, SpaceContext, space_editor, space_viewer
from app.core.errors import AppError
from app.models import Page
from app.repositories import pages as page_repo
from app.schemas.content import PageCreate, PageMove, PageOut, PageUpdate, TreeNode
from app.services import page_service, trash_service

router = APIRouter(prefix="/spaces/{space}/pages", tags=["pages"])

PageId = Annotated[uuid.UUID, Path()]
Slug = Annotated[str, Path(pattern=r"^[a-z0-9-]{1,80}$")]


def _ancestors(db: Db, current: SpaceContext, page: Page) -> list[TreeNode]:
    chain: list[TreeNode] = []
    parent_id = page.parent_id
    while parent_id is not None:
        parent = page_repo.get_live(db, current.space.id, parent_id)
        if parent is None:
            break
        chain.insert(
            0,
            TreeNode(
                id=parent.id,
                parent_id=parent.parent_id,
                slug=parent.slug,
                title=parent.title,
                position=parent.position,
                depth=parent.depth,
            ),
        )
        parent_id = parent.parent_id
    return chain


def page_out(db: Db, current: SpaceContext, page: Page, response: Response) -> PageOut:
    loaded = page_service.load(db, current.space, page)
    response.headers["ETag"] = f'"{loaded.revision.id}"'
    return PageOut(
        id=page.id,
        space_key=current.space.key,
        parent_id=page.parent_id,
        slug=page.slug,
        title=page.title,
        body=loaded.revision.body,
        revision_id=loaded.revision.id,
        revision_number=loaded.revision.number,
        updated_at=loaded.revision.created_at,
        updated_by=loaded.author,
        ancestors=_ancestors(db, current, page),
        is_home=page.id == current.space.home_page_id,
        favorite=page_repo.get_favorite(db, current.principal.user.id, page.id) is not None,
    )


def live_page(db: Db, current: SpaceContext, page_id: uuid.UUID) -> Page:
    page = page_repo.get_live(db, current.space.id, page_id)
    if page is None:
        raise AppError(404, "NOT_FOUND", "Not found")
    return page


def _expected_revision(if_match: str | None) -> uuid.UUID:
    if if_match is None:
        raise AppError(
            428, "PRECONDITION_REQUIRED", "If-Match header with the revision id required"
        )
    value = if_match.strip().removeprefix("W/").strip('"')
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise AppError(412, "STALE_REVISION", "Unknown revision") from exc


@router.post("", status_code=status.HTTP_201_CREATED, dependencies=[Depends(space_editor)])
def create_page(body: PageCreate, current: CurrentSpace, response: Response, db: Db) -> PageOut:
    page = page_service.create_page(
        db,
        current.space,
        current.principal.user.id,
        title=body.title,
        body=body.body,
        message=body.message,
        parent_id=body.parent_id,
    )
    db.commit()
    return page_out(db, current, page, response)


@router.get("/by-slug/{slug}", dependencies=[Depends(space_viewer)])
def get_page_by_slug(slug: Slug, current: CurrentSpace, response: Response, db: Db) -> PageOut:
    page = page_repo.get_live_by_slug(db, current.space.id, slug)
    if page is None:
        raise AppError(404, "NOT_FOUND", "Not found")
    return page_out(db, current, page, response)


@router.get("/{page_id}", dependencies=[Depends(space_viewer)])
def get_page(page_id: PageId, current: CurrentSpace, response: Response, db: Db) -> PageOut:
    return page_out(db, current, live_page(db, current, page_id), response)


@router.put("/{page_id}", dependencies=[Depends(space_editor)])
def update_page(
    page_id: PageId,
    body: PageUpdate,
    current: CurrentSpace,
    response: Response,
    db: Db,
    if_match: Annotated[str | None, Header(alias="If-Match", max_length=100)] = None,
) -> PageOut:
    page = page_service.update_page(
        db,
        current.space,
        current.principal.user.id,
        page_id,
        expected_revision=_expected_revision(if_match),
        title=body.title,
        body=body.body,
        message=body.message,
    )
    db.commit()
    return page_out(db, current, page, response)


@router.delete(
    "/{page_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(space_editor)]
)
def delete_page(page_id: PageId, current: CurrentSpace, db: Db, actor: CurrentActor) -> None:
    trash_service.trash_page(db, current.space, page_id, actor)


@router.post("/{page_id}/move", dependencies=[Depends(space_editor)])
def move_page(
    page_id: PageId, body: PageMove, current: CurrentSpace, response: Response, db: Db
) -> PageOut:
    page = page_service.move_page(
        db, current.space, page_id, parent_id=body.parent_id, position=body.position
    )
    db.commit()
    return page_out(db, current, page, response)
