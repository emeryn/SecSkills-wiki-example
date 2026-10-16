"""Shared schema building blocks."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

MAX_PAGE_SIZE = 100

Username = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=2, max_length=64, pattern=r"^[A-Za-z0-9._-]+$"
    ),
]
Email = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        max_length=254,
        pattern=r"^[^@\s<>\"'\r\n]+@[^@\s<>\"'\r\n]+\.[^@\s<>\"'\r\n]+$",
    ),
]
DisplayName = Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)]
Password = Annotated[str, StringConstraints(min_length=1, max_length=1024)]
Code = Annotated[str, StringConstraints(strip_whitespace=True, min_length=6, max_length=32)]
Token = Annotated[
    str, StringConstraints(min_length=20, max_length=200, pattern=r"^[A-Za-z0-9_-]+$")
]


class StrictModel(BaseModel):
    """Request bodies: unknown fields are rejected (no mass assignment)."""

    model_config = ConfigDict(extra="forbid")


class Page[T](BaseModel):
    items: list[T]
    total: int
    page: int
    page_size: int


class PageParams(StrictModel):
    page: int = Field(1, ge=1, le=100_000)
    page_size: int = Field(25, ge=1, le=MAX_PAGE_SIZE)
