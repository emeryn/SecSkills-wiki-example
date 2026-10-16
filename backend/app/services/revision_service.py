"""Revision history: line diff between two revisions and restore as a new revision."""

import difflib
import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.crypto import normalize
from app.core.errors import AppError
from app.models import Page, Revision, Space
from app.repositories import pages as page_repo
from app.services import audit_service, page_service, search_service
from app.services.audit_service import Actor


@dataclass(frozen=True)
class DiffLine:
    op: str  # "equal" | "insert" | "delete"
    text: str
    old_number: int | None
    new_number: int | None


def get_revision(db: Session, page: Page, revision_id: uuid.UUID) -> Revision:
    revision = page_repo.get_revision(db, page.id, revision_id)
    if revision is None:
        raise AppError(404, "NOT_FOUND", "Not found")
    return revision


def diff(old: Revision, new: Revision) -> list[DiffLine]:
    """Line diff of ``old`` → ``new`` (title included as the first line)."""
    old_lines = [f"# {old.title}", *old.body.splitlines()]
    new_lines = [f"# {new.title}", *new.body.splitlines()]
    matcher = difflib.SequenceMatcher(a=old_lines, b=new_lines, autojunk=False)
    lines: list[DiffLine] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            lines.extend(
                DiffLine("equal", old_lines[i], i + 1, j1 + (i - i1) + 1) for i in range(i1, i2)
            )
            continue
        lines.extend(DiffLine("delete", old_lines[i], i + 1, None) for i in range(i1, i2))
        lines.extend(DiffLine("insert", new_lines[j], None, j + 1) for j in range(j1, j2))
    return lines


def restore(
    db: Session,
    space: Space,
    page: Page,
    revision_id: uuid.UUID,
    author_id: uuid.UUID,
    actor: Actor,
) -> Page:
    """Copy an old revision into a new one; history is never rewritten."""
    old = get_revision(db, page, revision_id)
    if normalize(old.title) != page.title_norm:
        page_service.ensure_title_free(db, space.id, old.title, except_id=page.id)
    page.title = old.title
    page.title_norm = normalize(old.title)
    revision = Revision(
        id=uuid.uuid4(),
        page_id=page.id,
        number=page_repo.max_revision_number(db, page.id) + 1,
        author_id=author_id,
        title=old.title,
        body=old.body,
        message=f"Restored revision {old.number}",
        restored_from_id=old.id,
    )
    db.add(revision)
    db.flush()
    page.current_revision_id = revision.id
    search_service.refresh_vector(db, page.id)
    audit_service.record(
        db,
        actor,
        "revision.restored",
        target_type="page",
        target_id=page.id,
        after={"space": space.key, "restored_number": old.number, "new_number": revision.number},
    )
    db.commit()
    return page
