"""User administration."""

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import Ctx, CurrentActor, CurrentPrincipal, Db, require
from app.core.context import AppContext
from app.core.errors import AppError
from app.core.permissions import Permission
from app.models import User
from app.repositories import sessions as session_repo
from app.repositories import users as user_repo
from app.schemas.admin import (
    Count,
    GroupRef,
    Link,
    UserCreate,
    UserCreated,
    UserDetail,
    UserListParams,
    UserOut,
    UserUpdate,
)
from app.schemas.common import Page
from app.services import mfa_service, session_service, user_admin_service
from app.services.user_profile import email_index, read_profile

router = APIRouter(prefix="/users", tags=["admin"])

read = require(Permission.USERS_READ)
manage = require(Permission.USERS_MANAGE)
manage_recent = require(Permission.USERS_MANAGE, recent=True)


def _out(ctx: AppContext, user: User) -> UserOut:
    profile = read_profile(ctx.cipher, user)
    return UserOut(
        id=user.id,
        username=user.username,
        email=profile.email,
        display_name=profile.display_name,
        role=user.global_role,
        status=user.status,
        auth_source=user.auth_source,
        created_at=user.created_at,
        last_login_at=user.last_login_at,
    )


@router.get("", dependencies=[Depends(read)])
def list_users(params: Annotated[UserListParams, Query()], db: Db, ctx: Ctx) -> Page[UserOut]:
    query = (params.q or "").strip()
    users, total = user_repo.search_users(
        db,
        username_prefix=query if query and "@" not in query else None,
        email_bidx=email_index(ctx.cipher, query) if "@" in query else None,
        role=params.role,
        status=params.status,
        sort=params.sort,
        descending=params.order == "desc",
        page=params.page,
        page_size=params.page_size,
    )
    return Page(
        items=[_out(ctx, u) for u in users],
        total=total,
        page=params.page,
        page_size=params.page_size,
    )


@router.post("", status_code=status.HTTP_201_CREATED, dependencies=[Depends(manage)])
def create_user(body: UserCreate, db: Db, ctx: Ctx, actor: CurrentActor) -> UserCreated:
    user, link, expires_at = user_admin_service.create_user(
        db,
        ctx,
        username=body.username,
        email=body.email,
        display_name=body.display_name,
        role=body.role,
        actor=actor,
    )
    return UserCreated(user=_out(ctx, user), invitation=Link(url=link, expires_at=expires_at))


@router.get("/{user_id}", dependencies=[Depends(read)])
def get_user(user_id: uuid.UUID, db: Db, ctx: Ctx) -> UserDetail:
    user = user_admin_service.get_user(db, user_id)
    return UserDetail(
        **_out(ctx, user).model_dump(),
        mfa_enrolled=mfa_service.has_mfa(db, user.id),
        active_sessions=len(session_repo.list_active_for_user(db, user.id, datetime.now(UTC))),
        groups=[GroupRef(id=g.id, name=g.name) for g in user_repo.groups_of_user(db, user.id)],
    )


@router.patch("/{user_id}", dependencies=[Depends(manage)])
def update_user(
    user_id: uuid.UUID,
    body: UserUpdate,
    principal: CurrentPrincipal,
    db: Db,
    ctx: Ctx,
    actor: CurrentActor,
) -> UserOut:
    changes = {name: getattr(body, name) for name in body.model_fields_set}
    if {"role", "status"} & changes.keys() and not session_service.recently_authenticated(
        ctx, principal.session
    ):
        raise AppError(401, "REAUTH_REQUIRED", "Confirm your identity to continue")
    if changes.get("role") is None:
        changes.pop("role", None)
    if changes.get("status") is None:
        changes.pop("status", None)
    user = user_admin_service.get_user(db, user_id)
    updated = user_admin_service.update_user(db, ctx, principal, user, changes=changes, actor=actor)
    return _out(ctx, updated)


@router.post("/{user_id}/reset-link", dependencies=[Depends(manage_recent)])
def reset_link(user_id: uuid.UUID, db: Db, ctx: Ctx, actor: CurrentActor) -> Link:
    user = user_admin_service.get_user(db, user_id)
    url, expires_at = user_admin_service.reset_link(db, ctx, user, actor)
    return Link(url=url, expires_at=expires_at)


@router.post("/{user_id}/revoke-sessions", dependencies=[Depends(manage)])
def revoke_sessions(user_id: uuid.UUID, db: Db, actor: CurrentActor) -> Count:
    user = user_admin_service.get_user(db, user_id)
    return Count(count=user_admin_service.revoke_sessions(db, user, actor))


@router.post(
    "/{user_id}/reset-mfa",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(manage_recent)],
)
def reset_mfa(user_id: uuid.UUID, principal: CurrentPrincipal, db: Db, actor: CurrentActor) -> None:
    user = user_admin_service.get_user(db, user_id)
    user_admin_service.reset_mfa(db, principal, user, actor)
