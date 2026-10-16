"""Group administration."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import Ctx, CurrentActor, Db, require
from app.core.context import AppContext
from app.core.permissions import Permission
from app.models import Group
from app.repositories import users as user_repo
from app.schemas.admin import (
    GroupCreate,
    GroupDetail,
    GroupListParams,
    GroupOut,
    GroupUpdate,
    MemberOut,
)
from app.schemas.common import Page
from app.services import group_service
from app.services.user_profile import read_profile

router = APIRouter(prefix="/groups", tags=["admin"])

read = require(Permission.GROUPS_READ)
manage = require(Permission.GROUPS_MANAGE)


def _out(group: Group, member_count: int) -> GroupOut:
    return GroupOut(
        id=group.id,
        name=group.name,
        description=group.description,
        source=group.source,
        member_count=member_count,
        created_at=group.created_at,
    )


def _detail(db: Db, ctx: AppContext, group: Group) -> GroupDetail:
    members = user_repo.group_members(db, group.id)
    return GroupDetail(
        **_out(group, len(members)).model_dump(),
        members=[
            MemberOut(
                id=m.id, username=m.username, display_name=read_profile(ctx.cipher, m).display_name
            )
            for m in members
        ],
    )


@router.get("", dependencies=[Depends(read)])
def list_groups(params: Annotated[GroupListParams, Query()], db: Db) -> Page[GroupOut]:
    groups, total = user_repo.search_groups(
        db,
        name_contains=(params.q or "").strip() or None,
        sort=params.sort,
        descending=params.order == "desc",
        page=params.page,
        page_size=params.page_size,
    )
    counts = user_repo.member_counts(db, [g.id for g in groups])
    return Page(
        items=[_out(g, counts.get(g.id, 0)) for g in groups],
        total=total,
        page=params.page,
        page_size=params.page_size,
    )


@router.post("", status_code=status.HTTP_201_CREATED, dependencies=[Depends(manage)])
def create_group(body: GroupCreate, db: Db, actor: CurrentActor) -> GroupOut:
    return _out(group_service.create_group(db, body.name, body.description, actor), 0)


@router.get("/{group_id}", dependencies=[Depends(read)])
def get_group(group_id: uuid.UUID, db: Db, ctx: Ctx) -> GroupDetail:
    return _detail(db, ctx, group_service.get_group(db, group_id))


@router.patch("/{group_id}", dependencies=[Depends(manage)])
def update_group(
    group_id: uuid.UUID, body: GroupUpdate, db: Db, ctx: Ctx, actor: CurrentActor
) -> GroupDetail:
    changes = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
    group = group_service.update_group(db, group_service.get_group(db, group_id), changes, actor)
    return _detail(db, ctx, group)


@router.delete(
    "/{group_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(manage)]
)
def delete_group(group_id: uuid.UUID, db: Db, actor: CurrentActor) -> None:
    group_service.delete_group(db, group_service.get_group(db, group_id), actor)


@router.put(
    "/{group_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(manage)],
)
def add_member(group_id: uuid.UUID, user_id: uuid.UUID, db: Db, actor: CurrentActor) -> None:
    group_service.add_member(db, group_service.get_group(db, group_id), user_id, actor)


@router.delete(
    "/{group_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(manage)],
)
def remove_member(group_id: uuid.UUID, user_id: uuid.UUID, db: Db, actor: CurrentActor) -> None:
    group_service.remove_member(db, group_service.get_group(db, group_id), user_id, actor)
