"""Users and groups. Sort columns come from an allowlist; never from raw input."""

import uuid
from collections.abc import Sequence

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.models import Group, GroupMember, User

USER_SORTS = {
    "username": User.username,
    "created_at": User.created_at,
    "last_login_at": User.last_login_at,
}
GROUP_SORTS = {"name": Group.name, "created_at": Group.created_at}


def find_by_username(db: Session, username: str) -> User | None:
    return db.scalar(select(User).where(func.lower(User.username) == username.strip().lower()))


def find_by_email_index(db: Session, email_bidx: bytes) -> User | None:
    return db.scalar(select(User).where(User.email_bidx == email_bidx))


def get(db: Session, user_id: uuid.UUID) -> User | None:
    return db.get(User, user_id)


def count_active_admins(db: Session) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(User)
            .where(User.global_role == "admin", User.status == "active")
        )
        or 0
    )


def _paginate[T](
    db: Session, query: Select[T], page: int, page_size: int
) -> tuple[Sequence[T], int]:
    total = db.scalar(select(func.count()).select_from(query.order_by(None).subquery())) or 0
    items = db.scalars(query.offset((page - 1) * page_size).limit(page_size)).all()
    return items, total


def search_users(
    db: Session,
    *,
    username_prefix: str | None,
    email_bidx: bytes | None,
    role: str | None,
    status: str | None,
    sort: str,
    descending: bool,
    page: int,
    page_size: int,
) -> tuple[Sequence[User], int]:
    query = select(User)
    if email_bidx is not None:
        query = query.where(User.email_bidx == email_bidx)
    elif username_prefix:
        escaped = (
            username_prefix.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        )
        query = query.where(func.lower(User.username).like(f"{escaped}%", escape="\\"))
    if role is not None:
        query = query.where(User.global_role == role)
    if status is not None:
        query = query.where(User.status == status)
    column = USER_SORTS[sort]
    query = query.order_by(column.desc().nulls_last() if descending else column.asc(), User.id)
    return _paginate(db, query, page, page_size)


def find_group_by_name(db: Session, name: str) -> Group | None:
    return db.scalar(select(Group).where(func.lower(Group.name) == name.strip().lower()))


def get_group(db: Session, group_id: uuid.UUID) -> Group | None:
    return db.get(Group, group_id)


def search_groups(
    db: Session,
    *,
    name_contains: str | None,
    sort: str,
    descending: bool,
    page: int,
    page_size: int,
) -> tuple[Sequence[Group], int]:
    query = select(Group)
    if name_contains:
        escaped = (
            name_contains.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        )
        query = query.where(func.lower(Group.name).like(f"%{escaped}%", escape="\\"))
    column = GROUP_SORTS[sort]
    query = query.order_by(column.desc() if descending else column.asc(), Group.id)
    return _paginate(db, query, page, page_size)


def member_counts(db: Session, group_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, int]:
    rows = db.execute(
        select(GroupMember.group_id, func.count())
        .where(GroupMember.group_id.in_(group_ids))
        .group_by(GroupMember.group_id)
    ).all()
    return {group_id: count for group_id, count in rows}


def group_members(db: Session, group_id: uuid.UUID) -> Sequence[User]:
    return db.scalars(
        select(User)
        .join(GroupMember, GroupMember.user_id == User.id)
        .where(GroupMember.group_id == group_id)
        .order_by(User.username)
    ).all()


def get_membership(db: Session, group_id: uuid.UUID, user_id: uuid.UUID) -> GroupMember | None:
    return db.get(GroupMember, (group_id, user_id))


def groups_of_user(db: Session, user_id: uuid.UUID) -> Sequence[Group]:
    return db.scalars(
        select(Group)
        .join(GroupMember, GroupMember.group_id == Group.id)
        .where(GroupMember.user_id == user_id)
        .order_by(Group.name)
    ).all()
