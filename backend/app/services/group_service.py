"""Local groups and their members. Groups become space principals in the content phase."""

import uuid

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import Group, GroupMember, SpaceMember
from app.repositories import users as user_repo
from app.services import audit_service
from app.services.audit_service import Actor


def get_group(db: Session, group_id: uuid.UUID) -> Group:
    group = user_repo.get_group(db, group_id)
    if group is None:
        raise AppError(404, "NOT_FOUND", "Not found")
    return group


def _ensure_name_free(db: Session, name: str, except_id: uuid.UUID | None = None) -> None:
    existing = user_repo.find_group_by_name(db, name)
    if existing is not None and existing.id != except_id:
        raise AppError(409, "GROUP_NAME_TAKEN", "A group with this name already exists")


def create_group(db: Session, name: str, description: str, actor: Actor) -> Group:
    _ensure_name_free(db, name)
    group = Group(
        id=uuid.uuid4(), name=name.strip(), description=description.strip(), source="local"
    )
    db.add(group)
    audit_service.record(
        db,
        actor,
        "group.created",
        target_type="group",
        target_id=group.id,
        after={"name": group.name},
    )
    db.commit()
    return group


def update_group(db: Session, group: Group, changes: dict[str, str], actor: Actor) -> Group:
    if group.source != "local":
        raise AppError(409, "MANAGED_GROUP", "This group is managed by the directory")
    before = {"name": group.name, "description": group.description}
    if "name" in changes:
        _ensure_name_free(db, changes["name"], except_id=group.id)
        group.name = changes["name"].strip()
    if "description" in changes:
        group.description = changes["description"].strip()
    audit_service.record(
        db,
        actor,
        "group.updated",
        target_type="group",
        target_id=group.id,
        before=before,
        after={"name": group.name, "description": group.description},
    )
    db.commit()
    return group


def delete_group(db: Session, group: Group, actor: Actor) -> None:
    # Space memberships reference groups without a foreign key (principal_id is polymorphic).
    db.execute(
        delete(SpaceMember).where(
            SpaceMember.principal_type == "group", SpaceMember.principal_id == group.id
        )
    )
    audit_service.record(
        db,
        actor,
        "group.deleted",
        target_type="group",
        target_id=group.id,
        before={"name": group.name},
    )
    db.delete(group)
    db.commit()


def add_member(db: Session, group: Group, user_id: uuid.UUID, actor: Actor) -> None:
    if user_repo.get(db, user_id) is None:
        raise AppError(404, "NOT_FOUND", "Not found")
    if user_repo.get_membership(db, group.id, user_id) is not None:
        return
    db.add(GroupMember(group_id=group.id, user_id=user_id))
    audit_service.record(
        db,
        actor,
        "group.member_added",
        target_type="group",
        target_id=group.id,
        after={"user_id": str(user_id)},
    )
    db.commit()


def remove_member(db: Session, group: Group, user_id: uuid.UUID, actor: Actor) -> None:
    membership = user_repo.get_membership(db, group.id, user_id)
    if membership is None:
        raise AppError(404, "NOT_FOUND", "Not found")
    db.delete(membership)
    audit_service.record(
        db,
        actor,
        "group.member_removed",
        target_type="group",
        target_id=group.id,
        before={"user_id": str(user_id)},
    )
    db.commit()
