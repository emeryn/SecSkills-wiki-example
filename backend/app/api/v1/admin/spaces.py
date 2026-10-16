"""Space administration: every space with its settings, never its content."""

from fastapi import APIRouter, Depends

from app.api.deps import Db, require
from app.core.permissions import Permission
from app.repositories import spaces as space_repo
from app.schemas.content import AdminSpaceOut

router = APIRouter(prefix="/spaces", tags=["admin"])


@router.get("", dependencies=[Depends(require(Permission.SPACES_MANAGE))])
def list_all_spaces(db: Db) -> list[AdminSpaceOut]:
    counts = space_repo.member_counts(db)
    return [
        AdminSpaceOut(
            key=s.key,
            name=s.name,
            description=s.description,
            visibility=s.visibility,
            archived=s.archived_at is not None,
            home_page_id=s.home_page_id,
            role=None,
            member_count=counts.get(s.id, 0),
            created_at=s.created_at,
        )
        for s in space_repo.list_all(db)
    ]
