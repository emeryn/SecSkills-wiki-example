"""Spaces, members and the page tree of a space."""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import Ctx, CurrentActor, CurrentPrincipal, Db, authenticated, require
from app.api.space_access import (
    CurrentSpace,
    space_manager,
    space_reader_or_manager,
    space_viewer,
)
from app.core.errors import AppError
from app.core.permissions import Permission
from app.models import Space
from app.repositories import pages as page_repo
from app.repositories import spaces as space_repo
from app.repositories import users as user_repo
from app.schemas.content import (
    MemberOut,
    MemberSet,
    PrincipalOut,
    SpaceCreate,
    SpaceOut,
    SpaceUpdate,
    TreeNode,
)
from app.services import session_service, space_service

router = APIRouter(prefix="/spaces", tags=["spaces"])


def space_out(space: Space, role: str | None) -> SpaceOut:
    return SpaceOut(
        key=space.key,
        name=space.name,
        description=space.description,
        visibility=space.visibility,
        archived=space.archived_at is not None,
        home_page_id=space.home_page_id,
        role=role,
    )


@router.get("", dependencies=[Depends(authenticated)])
def list_spaces(
    principal: CurrentPrincipal, db: Db, include_archived: Annotated[bool, Query()] = False
) -> list[SpaceOut]:
    roles = space_repo.roles_by_space(db, principal.user.id)
    return [
        space_out(s, roles.get(s.id, "viewer"))
        for s in space_repo.list_readable(db, principal.user.id, include_archived)
    ]


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require(Permission.SPACES_MANAGE))],
)
def create_space(body: SpaceCreate, db: Db, actor: CurrentActor) -> SpaceOut:
    space = space_service.create_space(
        db,
        name=body.name,
        description=body.description,
        visibility=body.visibility,
        space_admin_id=body.space_admin_id,
        actor=actor,
    )
    return space_out(space, None)


@router.get("/{space}", dependencies=[Depends(space_reader_or_manager)])
def get_space(current: CurrentSpace) -> SpaceOut:
    return space_out(current.space, current.role)


@router.patch("/{space}", dependencies=[Depends(space_manager)])
def update_space(
    body: SpaceUpdate, current: CurrentSpace, db: Db, ctx: Ctx, actor: CurrentActor
) -> SpaceOut:
    changes = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
    widening = changes.get("visibility") == "internal" and current.space.visibility != "internal"
    if widening and not session_service.recently_authenticated(ctx, current.principal.session):
        raise AppError(401, "REAUTH_REQUIRED", "Confirm your identity to continue")
    space = space_service.update_space(db, current.space, changes, actor)
    return space_out(space, current.role)


@router.delete(
    "/{space}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(space_manager)]
)
def archive_space(current: CurrentSpace, db: Db, ctx: Ctx, actor: CurrentActor) -> None:
    """Archive (read-only, hidden from lists); content is kept."""
    if not session_service.recently_authenticated(ctx, current.principal.session):
        raise AppError(401, "REAUTH_REQUIRED", "Confirm your identity to continue")
    space_service.update_space(db, current.space, {"archived": True}, actor)


@router.get("/{space}/members", dependencies=[Depends(space_manager)])
def list_members(current: CurrentSpace, db: Db) -> list[MemberOut]:
    return [
        MemberOut(
            principal_type=m.principal_type, principal_id=m.principal_id, name=m.name, role=m.role
        )
        for m in space_service.list_members(db, current.space)
    ]


@router.put(
    "/{space}/members/{principal_type}/{principal_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(space_manager)],
)
def set_member(
    principal_type: Literal["user", "group"],
    principal_id: uuid.UUID,
    body: MemberSet,
    current: CurrentSpace,
    db: Db,
    actor: CurrentActor,
) -> None:
    space_service.set_member(db, current.space, principal_type, principal_id, body.role, actor)


@router.delete(
    "/{space}/members/{principal_type}/{principal_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(space_manager)],
)
def remove_member(
    principal_type: Literal["user", "group"],
    principal_id: uuid.UUID,
    current: CurrentSpace,
    db: Db,
    actor: CurrentActor,
) -> None:
    space_service.remove_member(db, current.space, principal_type, principal_id, actor)


@router.get("/{space}/pages", dependencies=[Depends(space_viewer)])
def page_tree(current: CurrentSpace, db: Db) -> list[TreeNode]:
    return [
        TreeNode(
            id=p.id,
            parent_id=p.parent_id,
            slug=p.slug,
            title=p.title,
            position=p.position,
            depth=p.depth,
        )
        for p in page_repo.live_pages(db, current.space.id)
    ]


@router.get("/{space}/principals", dependencies=[Depends(space_manager)])
def search_principals(
    db: Db, q: Annotated[str, Query(min_length=2, max_length=64)]
) -> list[PrincipalOut]:
    """Users and groups to add as members; restricted to the space's managers."""
    users, _ = user_repo.search_users(
        db,
        username_prefix=q,
        email_bidx=None,
        role=None,
        status="active",
        sort="username",
        descending=False,
        page=1,
        page_size=10,
    )
    groups, _ = user_repo.search_groups(
        db, name_contains=q, sort="name", descending=False, page=1, page_size=10
    )
    return [
        PrincipalOut(principal_type="user", principal_id=u.id, name=u.username) for u in users
    ] + [PrincipalOut(principal_type="group", principal_id=g.id, name=g.name) for g in groups]
