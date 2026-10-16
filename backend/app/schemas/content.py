"""Spaces, pages, revisions, trash, favorites and recent changes."""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

from app.schemas.common import StrictModel

SpaceRole = Literal["viewer", "editor", "space_admin"]
Visibility = Literal["restricted", "internal"]
# Page body max 1 MB, title max 200, revision message max 500 (specification).
Title = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, max_length=200, pattern=r"^[^\x00-\x1f\x7f]+$"
    ),
]
Body = Annotated[str, StringConstraints(max_length=1_000_000)]
Message = Annotated[
    str, StringConstraints(strip_whitespace=True, max_length=500, pattern=r"^[^\x00-\x1f\x7f]*$")
]
SpaceName = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, max_length=100, pattern=r"^[^\x00-\x1f\x7f<>]+$"
    ),
]


class SpaceCreate(StrictModel):
    name: SpaceName
    description: str = Field("", max_length=500)
    visibility: Visibility = "restricted"
    space_admin_id: uuid.UUID


class SpaceUpdate(StrictModel):
    name: SpaceName | None = None
    description: str | None = Field(None, max_length=500)
    visibility: Visibility | None = None
    archived: bool | None = None


class SpaceOut(BaseModel):
    key: str
    name: str
    description: str
    visibility: Visibility
    archived: bool
    home_page_id: uuid.UUID | None
    role: SpaceRole | None


class AdminSpaceOut(SpaceOut):
    member_count: int
    created_at: datetime


class MemberOut(BaseModel):
    principal_type: Literal["user", "group"]
    principal_id: uuid.UUID
    name: str
    role: SpaceRole


class PrincipalOut(BaseModel):
    principal_type: Literal["user", "group"]
    principal_id: uuid.UUID
    name: str


class MemberSet(StrictModel):
    role: SpaceRole


class TreeNode(BaseModel):
    id: uuid.UUID
    parent_id: uuid.UUID | None
    slug: str
    title: str
    position: int
    depth: int


class PageCreate(StrictModel):
    title: Title
    body: Body = ""
    message: Message = ""
    parent_id: uuid.UUID | None = None


class PageUpdate(StrictModel):
    title: Title
    body: Body
    message: Message = ""


class PageMove(StrictModel):
    parent_id: uuid.UUID | None
    position: int = Field(ge=0, le=100_000)


class PageOut(BaseModel):
    id: uuid.UUID
    space_key: str
    parent_id: uuid.UUID | None
    slug: str
    title: str
    body: str
    revision_id: uuid.UUID
    revision_number: int
    updated_at: datetime
    updated_by: str | None
    ancestors: list[TreeNode]
    is_home: bool
    favorite: bool


class RevisionOut(BaseModel):
    id: uuid.UUID
    number: int
    title: str
    message: str
    author: str | None
    created_at: datetime
    restored_from_id: uuid.UUID | None


class RevisionDetail(RevisionOut):
    body: str


class DiffLineOut(BaseModel):
    op: Literal["equal", "insert", "delete"]
    text: str
    old_number: int | None
    new_number: int | None


class DiffOut(BaseModel):
    old: RevisionOut
    new: RevisionOut
    lines: list[DiffLineOut]


class TrashItem(BaseModel):
    id: uuid.UUID
    title: str
    deleted_at: datetime
    deleted_by: str | None
    pages: int
    purge_after: datetime


class ChangeOut(BaseModel):
    page_id: uuid.UUID
    space_key: str
    space_name: str
    slug: str
    title: str
    revision_number: int
    message: str
    author: str | None
    created_at: datetime


class FavoriteOut(BaseModel):
    page_id: uuid.UUID
    space_key: str
    space_name: str
    slug: str
    title: str


class SnippetSegment(BaseModel):
    text: str
    highlight: bool


class SearchHit(BaseModel):
    page_id: uuid.UUID
    space_key: str
    space_name: str
    slug: str
    title: str
    snippet: list[SnippetSegment]
    updated_at: datetime


class AttachmentOut(BaseModel):
    id: uuid.UUID
    filename: str
    content_type: str
    size_bytes: int
    inline: bool
    uploaded_by: str | None
    created_at: datetime
    url: str
