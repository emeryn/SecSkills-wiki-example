"""Markdown export of a page subtree or a whole space as a zip archive.

Archive names come only from server-generated slugs and sanitized attachment names, and are
checked again before writing (zip-slip safe). ``[[Title]]`` links and attachment URLs are
rewritten to relative paths inside the archive.
"""

import posixpath
import re
import tempfile
import uuid
import zipfile
from collections.abc import Sequence
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.crypto import normalize
from app.models import Attachment, Page, Revision, Space
from app.repositories import pages as page_repo
from app.services import attachment_service

_WIKI_LINK = re.compile(r"\[\[([^\]\n|]{1,200})(?:\|([^\]\n]{1,200}))?\]\]")
_ATTACHMENT_URL = re.compile(r"/api/v1/attachments/([0-9a-f-]{36})")
_SAFE_ARCNAME = re.compile(r"^[a-z0-9-]+(?:/[a-z0-9-]+)*\.md$|^_attachments/[\w .()\-]+$")
ATTACHMENTS_DIR = "_attachments"


def _paths(pages: Sequence[Page], root: Page | None) -> dict[uuid.UUID, str]:
    """``<parent-slug>/<slug>.md`` relative to the export root."""
    by_id = {p.id: p for p in pages}
    paths: dict[uuid.UUID, str] = {}
    for page in pages:
        parts, current = [page.slug], page
        while current.parent_id in by_id and (root is None or current.id != root.id):
            current = by_id[current.parent_id]
            parts.insert(0, current.slug)
        paths[page.id] = "/".join(parts) + ".md"
    return paths


def _relative(target: str, source: str) -> str:
    return posixpath.relpath(target, posixpath.dirname(source) or ".")


def _check_arcname(name: str) -> str:
    if not _SAFE_ARCNAME.match(name) or ".." in name.split("/"):
        raise ValueError(f"Unsafe archive name: {name!r}")
    return name


def build_archive(db: Session, storage_dir: Path, space: Space, root: Page | None) -> Path:
    """Write the archive to a temporary file and return its path (the caller deletes it)."""
    if root is None:
        pages = list(page_repo.live_pages(db, space.id))
    else:
        pages = [p for p in page_repo.subtree(db, root.id) if p.deleted_at is None]
    paths = _paths(pages, root)
    by_title = {p.title_norm: paths[p.id] for p in pages}
    attachments = db.scalars(
        select(Attachment).where(Attachment.page_id.in_([p.id for p in pages]))
    ).all()
    attachment_paths = {
        str(
            a.id
        ): f"{ATTACHMENTS_DIR}/{str(a.id)[:8]}-{attachment_service.sanitize_filename(a.filename)}"
        for a in attachments
    }

    handle = tempfile.NamedTemporaryFile(prefix="export-", suffix=".zip", delete=False)  # noqa: SIM115
    handle.close()
    with zipfile.ZipFile(handle.name, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for page in pages:
            revision = (
                db.get(Revision, page.current_revision_id) if page.current_revision_id else None
            )
            source = paths[page.id]

            def wiki_link(match: re.Match[str], source: str = source) -> str:
                title, label = match.group(1).strip(), (match.group(2) or match.group(1)).strip()
                target = by_title.get(normalize(title))
                return f"[{label}]({_relative(target, source)})" if target else label

            def attachment_link(match: re.Match[str], source: str = source) -> str:
                target = attachment_paths.get(match.group(1))
                return _relative(target, source) if target else match.group(0)

            body = revision.body if revision else ""
            body = _ATTACHMENT_URL.sub(attachment_link, _WIKI_LINK.sub(wiki_link, body))
            archive.writestr(_check_arcname(source), f"# {page.title}\n\n{body}\n")
        for attachment in attachments:
            archive.write(
                attachment_service.path_of(storage_dir, attachment),
                _check_arcname(attachment_paths[str(attachment.id)]),
            )
    return Path(handle.name)
