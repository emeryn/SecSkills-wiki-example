"""Spaces and their memberships."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import Space, SpaceMember
from app.repositories import spaces as space_repo
from app.repositories import users as user_repo
from app.services import audit_service, page_service
from app.services.audit_service import Actor
from app.services.slug import unique_slug


@dataclass(frozen=True)
class MemberView:
    principal_type: str
    principal_id: uuid.UUID
    name: str
    role: str


def create_space(
    db: Session,
    *,
    name: str,
    description: str,
    visibility: str,
    space_admin_id: uuid.UUID,
    actor: Actor,
) -> Space:
    """Create a space, its first space administrator and its home page."""
    admin = user_repo.get(db, space_admin_id)
    if admin is None or admin.status != "active":
        raise AppError(422, "INVALID_SPACE_ADMIN", "The space administrator must be an active user")
    space = Space(
        id=uuid.uuid4(),
        key=unique_slug(name, 40, "space", lambda c: space_repo.key_exists(db, c)),
        name=name.strip(),
        description=description.strip(),
        visibility=visibility,
        created_by=actor.user_id,
    )
    db.add(space)
    db.flush()
    db.add(
        SpaceMember(
            space_id=space.id, principal_type="user", principal_id=admin.id, role="space_admin"
        )
    )
    home = page_service.create_page(
        db,
        space,
        actor.user_id or admin.id,
        title=space.name,
        body=f"# {space.name}\n",
        message="Space created",
    )
    space.home_page_id = home.id
    audit_service.record(
        db,
        actor,
        "space.created",
        target_type="space",
        target_id=space.id,
        after={
            "key": space.key,
            "name": space.name,
            "visibility": visibility,
            "space_admin": str(admin.id),
        },
    )
    db.commit()
    return space


def update_space(db: Session, space: Space, changes: dict[str, object], actor: Actor) -> Space:
    before = {
        "name": space.name,
        "description": space.description,
        "visibility": space.visibility,
        "archived": space.archived_at is not None,
    }
    if "name" in changes:
        space.name = str(changes["name"]).strip()
    if "description" in changes:
        space.description = str(changes["description"]).strip()
    if "visibility" in changes:
        space.visibility = str(changes["visibility"])
    if "archived" in changes:
        space.archived_at = datetime.now(UTC) if changes["archived"] else None
    after = {
        "name": space.name,
        "description": space.description,
        "visibility": space.visibility,
        "archived": space.archived_at is not None,
    }
    audit_service.record(
        db,
        actor,
        "space.updated",
        target_type="space",
        target_id=space.id,
        before=before,
        after=after,
    )
    db.commit()
    return space


def list_members(db: Session, space: Space) -> list[MemberView]:
    views = []
    for member in space_repo.members(db, space.id):
        if member.principal_type == "user":
            user = user_repo.get(db, member.principal_id)
            name = user.username if user else "?"
        else:
            group = user_repo.get_group(db, member.principal_id)
            name = group.name if group else "?"
        views.append(MemberView(member.principal_type, member.principal_id, name, member.role))
    return views


def set_member(
    db: Session, space: Space, principal_type: str, principal_id: uuid.UUID, role: str, actor: Actor
) -> None:
    exists = (
        user_repo.get(db, principal_id)
        if principal_type == "user"
        else user_repo.get_group(db, principal_id)
    )
    if exists is None:
        raise AppError(404, "NOT_FOUND", "Not found")
    member = space_repo.get_member(db, space.id, principal_type, principal_id)
    before = {"role": member.role} if member else None
    if member is None:
        db.add(
            SpaceMember(
                space_id=space.id,
                principal_type=principal_type,
                principal_id=principal_id,
                role=role,
            )
        )
    else:
        if member.role == "space_admin" and role != "space_admin":
            _keep_one_space_admin(db, space)
        member.role = role
    audit_service.record(
        db,
        actor,
        "space.member_set",
        target_type="space",
        target_id=space.id,
        before=before,
        after={"principal": f"{principal_type}:{principal_id}", "role": role},
    )
    db.commit()


def remove_member(
    db: Session, space: Space, principal_type: str, principal_id: uuid.UUID, actor: Actor
) -> None:
    member = space_repo.get_member(db, space.id, principal_type, principal_id)
    if member is None:
        raise AppError(404, "NOT_FOUND", "Not found")
    if member.role == "space_admin":
        _keep_one_space_admin(db, space)
    db.delete(member)
    audit_service.record(
        db,
        actor,
        "space.member_removed",
        target_type="space",
        target_id=space.id,
        before={"principal": f"{principal_type}:{principal_id}", "role": member.role},
    )
    db.commit()


def _keep_one_space_admin(db: Session, space: Space) -> None:
    if space_repo.count_space_admins(db, space.id) <= 1:
        raise AppError(409, "LAST_SPACE_ADMIN", "A space needs at least one space administrator")
