"""The signed-in user's API keys (MCP clients)."""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path, status
from pydantic import BaseModel, Field

from app.api.deps import CurrentActor, CurrentPrincipal, Db, authenticated, recent_auth
from app.models import ApiKey
from app.schemas.common import StrictModel
from app.services import api_key_service

router = APIRouter(prefix="/me/api-keys", tags=["account"])

Scope = Literal["pages:read", "pages:write", "admin"]


class ApiKeyCreate(StrictModel):
    name: str = Field(min_length=1, max_length=100, pattern=r"^[^\r\n<>]+$")
    scopes: list[Scope] = Field(min_length=1, max_length=3)
    days: int = Field(90, ge=1, le=api_key_service.MAX_DAYS)


class ApiKeyOut(BaseModel):
    id: uuid.UUID
    name: str
    prefix: str
    scopes: list[str]
    status: Literal["active", "expired", "revoked"]
    created_at: datetime
    expires_at: datetime
    last_used_at: datetime | None


class ApiKeyCreated(ApiKeyOut):
    # The only time the secret is returned.
    secret: str


def _out(key: ApiKey) -> ApiKeyOut:
    return ApiKeyOut(
        id=key.id,
        name=key.name,
        prefix=key.prefix,
        scopes=key.scopes,
        status=api_key_service.status(key),
        created_at=key.created_at,
        expires_at=key.expires_at,
        last_used_at=key.last_used_at,
    )


@router.get("", dependencies=[Depends(authenticated)])
def list_keys(principal: CurrentPrincipal, db: Db) -> list[ApiKeyOut]:
    return [_out(key) for key in api_key_service.list_for(db, principal.user.id)]


@router.post("", status_code=status.HTTP_201_CREATED, dependencies=[Depends(recent_auth)])
def create_key(
    body: ApiKeyCreate, principal: CurrentPrincipal, db: Db, actor: CurrentActor
) -> ApiKeyCreated:
    issued = api_key_service.issue(
        db, principal.user, actor, name=body.name, scopes=list(body.scopes), days=body.days
    )
    return ApiKeyCreated(**_out(issued.key).model_dump(), secret=issued.secret)


@router.delete(
    "/{key_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(authenticated)]
)
def revoke_key(
    key_id: Annotated[uuid.UUID, Path()], principal: CurrentPrincipal, db: Db, actor: CurrentActor
) -> None:
    api_key_service.revoke(db, principal.user.id, key_id, actor)
