"""Recent changes and favorites, filtered by the spaces the caller can read."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import CurrentPrincipal, Db, authenticated
from app.core.errors import AppError
from app.models import Favorite
from app.repositories import pages as page_repo
from app.repositories import spaces as space_repo
from app.schemas.content import ChangeOut, FavoriteOut

router = APIRouter(tags=["feed"])


@router.get("/recent-changes", dependencies=[Depends(authenticated)])
def recent_changes(
    principal: CurrentPrincipal,
    db: Db,
    space: Annotated[str | None, Query(pattern=r"^[a-z0-9-]{1,40}$")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> list[ChangeOut]:
    space_id = None
    if space is not None:
        found = space_repo.get_by_key(db, space)
        if found is None or space_repo.role_in_space(db, principal.user.id, found) is None:
            raise AppError(404, "NOT_FOUND", "Not found")
        space_id = found.id
    return [
        ChangeOut(
            page_id=page.id,
            space_key=sp.key,
            space_name=sp.name,
            slug=page.slug,
            title=page.title,
            revision_number=revision.number,
            message=revision.message,
            author=author,
            created_at=revision.created_at,
        )
        for revision, page, sp, author in page_repo.recent_changes(
            db, principal.user.id, space_id, limit
        )
    ]


@router.get("/me/favorites", dependencies=[Depends(authenticated)])
def list_favorites(principal: CurrentPrincipal, db: Db) -> list[FavoriteOut]:
    return [
        FavoriteOut(
            page_id=page.id, space_key=sp.key, space_name=sp.name, slug=page.slug, title=page.title
        )
        for page, sp in page_repo.favorites(db, principal.user.id)
    ]


@router.put(
    "/me/favorites/{page_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(authenticated)],
)
def add_favorite(page_id: uuid.UUID, principal: CurrentPrincipal, db: Db) -> None:
    if page_repo.readable_live_page(db, principal.user.id, page_id) is None:
        raise AppError(404, "NOT_FOUND", "Not found")
    if page_repo.get_favorite(db, principal.user.id, page_id) is None:
        db.add(Favorite(user_id=principal.user.id, page_id=page_id))
        db.commit()


@router.delete(
    "/me/favorites/{page_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(authenticated)],
)
def remove_favorite(page_id: uuid.UUID, principal: CurrentPrincipal, db: Db) -> None:
    favorite = page_repo.get_favorite(db, principal.user.id, page_id)
    if favorite is None:
        raise AppError(404, "NOT_FOUND", "Not found")
    db.delete(favorite)
    db.commit()
