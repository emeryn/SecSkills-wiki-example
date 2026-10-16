"""Spaces and memberships, and the single "readable spaces" predicate reused by every query."""

import uuid
from collections.abc import Sequence

from sqlalchemy import ColumnElement, Select, and_, func, or_, select
from sqlalchemy.orm import Session

from app.models import GroupMember, Space, SpaceMember

ROLE_RANK = {"viewer": 1, "editor": 2, "space_admin": 3}


def _principal_filter(user_id: uuid.UUID) -> ColumnElement[bool]:
    groups = select(GroupMember.group_id).where(GroupMember.user_id == user_id)
    return or_(
        and_(SpaceMember.principal_type == "user", SpaceMember.principal_id == user_id),
        and_(SpaceMember.principal_type == "group", SpaceMember.principal_id.in_(groups)),
    )


def readable_space_ids(user_id: uuid.UUID) -> Select[uuid.UUID]:
    """Spaces the user may read: internal ones, plus restricted ones they are a member of.

    Global administrators get no implicit read access: being admin does not appear here.
    """
    member_of = select(SpaceMember.space_id).where(_principal_filter(user_id))
    return select(Space.id).where(or_(Space.visibility == "internal", Space.id.in_(member_of)))


def get_by_key(db: Session, key: str) -> Space | None:
    return db.scalar(select(Space).where(Space.key == key))


def key_exists(db: Session, key: str) -> bool:
    return db.scalar(select(Space.id).where(Space.key == key)) is not None


def roles_by_space(db: Session, user_id: uuid.UUID) -> dict[uuid.UUID, str]:
    """Highest membership role per space (direct or through groups)."""
    best: dict[uuid.UUID, str] = {}
    rows = db.execute(
        select(SpaceMember.space_id, SpaceMember.role).where(_principal_filter(user_id))
    )
    for space_id, role in rows:
        if ROLE_RANK[role] > ROLE_RANK.get(best.get(space_id, ""), 0):
            best[space_id] = role
    return best


def role_in_space(db: Session, user_id: uuid.UUID, space: Space) -> str | None:
    rows = db.scalars(
        select(SpaceMember.role).where(SpaceMember.space_id == space.id, _principal_filter(user_id))
    ).all()
    if rows:
        return max(rows, key=lambda role: ROLE_RANK[role])
    return "viewer" if space.visibility == "internal" else None


def list_readable(db: Session, user_id: uuid.UUID, include_archived: bool) -> Sequence[Space]:
    query = select(Space).where(Space.id.in_(readable_space_ids(user_id)))
    if not include_archived:
        query = query.where(Space.archived_at.is_(None))
    return db.scalars(query.order_by(func.lower(Space.name))).all()


def list_all(db: Session) -> Sequence[Space]:
    return db.scalars(select(Space).order_by(func.lower(Space.name))).all()


def members(db: Session, space_id: uuid.UUID) -> Sequence[SpaceMember]:
    return db.scalars(
        select(SpaceMember).where(SpaceMember.space_id == space_id).order_by(SpaceMember.created_at)
    ).all()


def member_counts(db: Session) -> dict[uuid.UUID, int]:
    rows = db.execute(select(SpaceMember.space_id, func.count()).group_by(SpaceMember.space_id))
    return {space_id: count for space_id, count in rows}


def get_member(
    db: Session, space_id: uuid.UUID, principal_type: str, principal_id: uuid.UUID
) -> SpaceMember | None:
    return db.get(SpaceMember, (space_id, principal_type, principal_id))


def count_space_admins(db: Session, space_id: uuid.UUID) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(SpaceMember)
            .where(SpaceMember.space_id == space_id, SpaceMember.role == "space_admin")
        )
        or 0
    )
