"""Full-text search across the pages the caller can read."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import CurrentPrincipal, Db, authenticated
from app.core.errors import AppError
from app.repositories import spaces as space_repo
from app.schemas.common import Page as PageOf
from app.schemas.content import SearchHit, SnippetSegment
from app.services import search_service

router = APIRouter(tags=["search"])

MAX_SEARCH_PAGE_SIZE = 50


@router.get("/search", dependencies=[Depends(authenticated)])
def search(
    principal: CurrentPrincipal,
    db: Db,
    q: Annotated[str, Query(min_length=1, max_length=200)],
    space: Annotated[str | None, Query(pattern=r"^[a-z0-9-]{1,40}$")] = None,
    page: Annotated[int, Query(ge=1, le=1000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=MAX_SEARCH_PAGE_SIZE)] = 20,
) -> PageOf[SearchHit]:
    space_id = None
    if space is not None:
        found = space_repo.get_by_key(db, space)
        if found is None or space_repo.role_in_space(db, principal.user.id, found) is None:
            raise AppError(404, "NOT_FOUND", "Not found")
        space_id = found.id
    hits, total = search_service.search(db, principal.user.id, q.strip(), space_id, page, page_size)
    return PageOf(
        items=[
            SearchHit(
                page_id=h.page.id,
                space_key=h.space.key,
                space_name=h.space.name,
                slug=h.page.slug,
                title=h.page.title,
                snippet=[SnippetSegment(text=s.text, highlight=s.highlight) for s in h.snippet],
                updated_at=h.revision.created_at,
            )
            for h in hits
        ],
        total=total,
        page=page,
        page_size=page_size,
    )
