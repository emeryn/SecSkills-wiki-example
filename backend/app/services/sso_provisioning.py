"""Accounts and space memberships from an identity provider (OIDC) or a directory (LDAP).

An external identity is matched by ``(source, external_id)`` only, never by username or email:
an IdP account can never take over a local account that happens to share its name. Space
memberships derived from groups are marked ``source = 'sso'`` and re-synchronized at each
sign-in; memberships granted by hand are never modified. The global role of an SSO account comes
from the admin groups alone, also re-synchronized at each sign-in.
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.context import AppContext
from app.core.crypto import normalize
from app.models import Space, SpaceMember, User
from app.repositories import sessions as session_repo
from app.repositories import users as user_repo
from app.repositories.spaces import ROLE_RANK
from app.schemas.settings import GroupMapping
from app.services import audit_service
from app.services.audit_service import Actor
from app.services.user_profile import email_index, new_user, read_profile, set_profile

logger = logging.getLogger(__name__)

Source = Literal["oidc", "ldap"]
_USERNAME = re.compile(r"^[A-Za-z0-9._-]{2,64}$")


class SsoError(Exception):
    """Sign-in refused for a reason recorded in the audit trail (never shown in detail)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class Identity:
    source: Source
    external_id: str
    username: str
    email: str | None = None
    display_name: str | None = None
    groups: list[str] = field(default_factory=list)


def find(db: Session, source: Source, external_id: str) -> User | None:
    return db.scalar(
        select(User).where(User.auth_source == source, User.external_id == external_id)
    )


def _provision(db: Session, ctx: AppContext, identity: Identity, actor: Actor) -> User:
    username = identity.username.strip()
    if not _USERNAME.match(username):
        raise SsoError("invalid_username")
    decoys = {normalize(name) for name in ctx.runtime.snapshot().security.decoy_usernames}
    if normalize(username) in decoys or user_repo.find_by_username(db, username) is not None:
        raise SsoError("username_taken")
    user = new_user(ctx.cipher, username)
    user.auth_source = identity.source
    user.external_id = identity.external_id
    db.add(user)
    db.flush()
    audit_service.record(
        db,
        actor,
        "user.provisioned",
        target_type="user",
        target_id=user.id,
        after={"username": username, "source": identity.source},
    )
    return user


def _update_profile(db: Session, ctx: AppContext, user: User, identity: Identity) -> None:
    profile = read_profile(ctx.cipher, user)
    email = identity.email.strip() if identity.email else None
    if email and email != profile.email:
        other = user_repo.find_by_email_index(db, email_index(ctx.cipher, email))
        if other is not None and other.id != user.id:
            logger.warning("SSO email already used by another account; not updated")
            email = profile.email
    display_name = (identity.display_name or "").strip()[:100] or profile.display_name
    if email != profile.email or display_name != profile.display_name:
        set_profile(ctx.cipher, user, email=email, display_name=display_name)


def desired_roles(db: Session, groups: list[str], mapping: list[GroupMapping]) -> dict[Space, str]:
    """Highest mapped role per space for the user's groups (case-insensitive group match)."""
    member_of = {normalize(group) for group in groups}
    wanted: dict[str, str] = {}
    for rule in mapping:
        if normalize(rule.group) in member_of and ROLE_RANK[rule.role] > ROLE_RANK.get(
            wanted.get(rule.space, ""), 0
        ):
            wanted[rule.space] = rule.role
    if not wanted:
        return {}
    spaces = db.scalars(select(Space).where(Space.key.in_(wanted))).all()
    unknown = set(wanted) - {space.key for space in spaces}
    if unknown:
        logger.warning("Group mapping names unknown spaces", extra={"spaces": sorted(unknown)})
    return {space: wanted[space.key] for space in spaces}


def sync_memberships(
    db: Session, user: User, groups: list[str], mapping: list[GroupMapping], actor: Actor
) -> None:
    """Make the user's ``sso`` memberships match the mapping; manual ones take precedence."""
    desired = {
        space.id: (space, role) for space, role in desired_roles(db, groups, mapping).items()
    }
    rows = db.scalars(
        select(SpaceMember).where(
            SpaceMember.principal_type == "user", SpaceMember.principal_id == user.id
        )
    ).all()
    manual = {row.space_id for row in rows if row.source != "sso"}
    current = {row.space_id: row for row in rows if row.source == "sso"}
    for space_id, row in current.items():
        target = desired.get(space_id)
        if target is None or space_id in manual:
            db.delete(row)
            _audit(db, actor, user, space_id, before=row.role, after=None)
        elif target[1] != row.role:
            _audit(db, actor, user, space_id, before=row.role, after=target[1])
            row.role = target[1]
    for space_id, (_, role) in desired.items():
        if space_id in manual or space_id in current:
            continue
        db.add(
            SpaceMember(
                space_id=space_id,
                principal_type="user",
                principal_id=user.id,
                role=role,
                source="sso",
            )
        )
        _audit(db, actor, user, space_id, before=None, after=role)


def _audit(
    db: Session, actor: Actor, user: User, space_id: object, before: str | None, after: str | None
) -> None:
    audit_service.record(
        db,
        actor,
        "space.member_synced",
        target_type="user",
        target_id=user.id,
        before={"space_id": str(space_id), "role": before} if before else None,
        after={"space_id": str(space_id), "role": after} if after else None,
    )


def sync_role(
    db: Session, user: User, groups: list[str], admin_groups: list[str], actor: Actor
) -> None:
    """Administrator exactly when a member of an admin group; never demotes the last admin."""
    member_of = {normalize(group) for group in groups}
    wanted = "admin" if any(normalize(g) in member_of for g in admin_groups) else "user"
    if wanted == user.global_role:
        return
    if wanted == "user" and user_repo.count_active_admins(db) <= 1:
        logger.error("Last active administrator left the admin groups; role kept")
        return
    before = user.global_role
    user.global_role = wanted
    # A privilege change ends the account's other sessions; this sign-in opens a new one.
    session_repo.revoke_all(db, user.id, datetime.now(UTC))
    audit_service.record(
        db,
        actor,
        "user.role_synced",
        severity="warning" if wanted == "admin" else "info",
        target_type="user",
        target_id=user.id,
        before={"role": before},
        after={"role": wanted, "source": user.auth_source},
    )


def sign_in_user(
    db: Session,
    ctx: AppContext,
    identity: Identity,
    *,
    auto_provision: bool,
    mapping: list[GroupMapping],
    actor: Actor,
    admin_groups: list[str] | None = None,
) -> User:
    """The local account for ``identity`` (created if allowed), updated and synchronized."""
    user = find(db, identity.source, identity.external_id)
    if user is None:
        if not auto_provision:
            raise SsoError("not_provisioned")
        user = _provision(db, ctx, identity, actor)
    if user.status != "active":
        raise SsoError("disabled")
    _update_profile(db, ctx, user, identity)
    sync_role(db, user, identity.groups, admin_groups or [], actor)
    sync_memberships(db, user, identity.groups, mapping, actor)
    return user
