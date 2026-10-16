"""Space-level authorization: the route's access policy plus the caller's role in the space."""

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Path, Request

from app.api.deps import Ctx, Db, authenticated
from app.core.errors import AppError
from app.core.permissions import AccessPolicy
from app.models import Space
from app.repositories import spaces as space_repo
from app.repositories.spaces import ROLE_RANK
from app.services.session_service import Principal

SpaceKey = Annotated[str, Path(pattern=r"^[a-z0-9-]{1,40}$")]


@dataclass(frozen=True)
class SpaceContext:
    principal: Principal
    space: Space
    # None when a global administrator manages a space they are not a member of.
    role: str | None

    def can(self, role: str) -> bool:
        return self.role is not None and ROLE_RANK[self.role] >= ROLE_RANK[role]


class SpaceAccess:
    """Requires ``min_role`` in the space named by the ``space`` path parameter.

    Without read access the space does not exist for the caller (404). ``admin_manages`` lets
    global administrators manage settings and members of any space, never read its pages.
    """

    def __init__(self, min_role: str, *, admin_manages: bool = False, write: bool = False) -> None:
        suffix = "+admin" if admin_manages else ""
        self.policy = AccessPolicy(f"space:{min_role}{suffix}", authenticated=True)
        self.min_role = min_role
        self.admin_manages = admin_manages
        self.write = write

    def __call__(self, space: SpaceKey, request: Request, db: Db, ctx: Ctx) -> SpaceContext:
        principal = authenticated(request, db, ctx)
        if principal is None:
            raise AppError(401, "UNAUTHENTICATED", "Sign in required")
        found = space_repo.get_by_key(db, space)
        role = space_repo.role_in_space(db, principal.user.id, found) if found else None
        managed_by_admin = self.admin_manages and principal.is_admin
        if found is None or (role is None and not managed_by_admin):
            raise AppError(404, "NOT_FOUND", "Not found")
        context = SpaceContext(principal=principal, space=found, role=role)
        if not managed_by_admin and not context.can(self.min_role):
            raise AppError(403, "FORBIDDEN", "You do not have permission to do this")
        if self.write and found.archived_at is not None:
            raise AppError(409, "SPACE_ARCHIVED", "This space is archived and read-only")
        request.state.space_context = context
        return context


def space_context(request: Request) -> SpaceContext:
    context: SpaceContext = request.state.space_context
    return context


CurrentSpace = Annotated[SpaceContext, Depends(space_context)]

space_viewer = SpaceAccess("viewer")
space_editor = SpaceAccess("editor", write=True)
space_admin = SpaceAccess("space_admin", write=True)
space_manager = SpaceAccess("space_admin", admin_manages=True)
space_reader_or_manager = SpaceAccess("viewer", admin_manages=True)
