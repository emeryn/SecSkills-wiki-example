"""User and group administration schemas."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.common import DisplayName, Email, PageParams, StrictModel, Username

Role = Literal["user", "admin"]
Status = Literal["active", "disabled"]


class UserListParams(PageParams):
    q: str | None = Field(None, max_length=254)
    role: Role | None = None
    status: Status | None = None
    sort: Literal["username", "created_at", "last_login_at"] = "username"
    order: Literal["asc", "desc"] = "asc"


class UserCreate(StrictModel):
    username: Username
    email: Email | None = None
    display_name: DisplayName | None = None
    role: Role = "user"


class UserUpdate(StrictModel):
    email: Email | None = None
    display_name: DisplayName | None = None
    role: Role | None = None
    status: Status | None = None


class UserOut(BaseModel):
    id: uuid.UUID
    username: str
    email: str | None
    display_name: str | None
    role: Role
    status: Status
    auth_source: str
    created_at: datetime
    last_login_at: datetime | None


class UserDetail(UserOut):
    mfa_enrolled: bool
    active_sessions: int
    groups: list[GroupRef]


class GroupRef(BaseModel):
    id: uuid.UUID
    name: str


class Link(BaseModel):
    url: str
    expires_at: datetime


class UserCreated(BaseModel):
    user: UserOut
    invitation: Link


class GroupListParams(PageParams):
    q: str | None = Field(None, max_length=100)
    sort: Literal["name", "created_at"] = "name"
    order: Literal["asc", "desc"] = "asc"


class GroupCreate(StrictModel):
    name: str = Field(min_length=1, max_length=100, pattern=r"^[^\r\n<>]+$")
    description: str = Field("", max_length=500)


class GroupUpdate(StrictModel):
    name: str | None = Field(None, min_length=1, max_length=100, pattern=r"^[^\r\n<>]+$")
    description: str | None = Field(None, max_length=500)


class GroupOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str
    source: str
    member_count: int
    created_at: datetime


class MemberOut(BaseModel):
    id: uuid.UUID
    username: str
    display_name: str | None


class GroupDetail(GroupOut):
    members: list[MemberOut]


class Count(BaseModel):
    count: int
