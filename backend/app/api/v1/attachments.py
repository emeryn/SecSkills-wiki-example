"""Attachments: list and upload per page; download and delete by id (never from the web root)."""

import uuid
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, UploadFile, status
from fastapi.responses import FileResponse

from app.api.deps import Ctx, CurrentActor, CurrentPrincipal, Db, authenticated
from app.api.space_access import CurrentSpace, space_editor, space_viewer
from app.api.v1.pages import PageId, live_page
from app.core.errors import AppError
from app.models import Attachment, Page
from app.repositories import pages as page_repo
from app.repositories import spaces as space_repo
from app.repositories.spaces import ROLE_RANK
from app.schemas.content import AttachmentOut
from app.services import attachment_service, audit_service
from app.services.session_service import Principal

router = APIRouter(tags=["attachments"])

UPLOAD_CHUNK = 64 * 1024
# Attachment responses can never run script, even if a browser ignored Content-Disposition.
ATTACHMENT_CSP = "default-src 'none'; img-src 'self'; sandbox"


def _out(db: Db, attachment: Attachment) -> AttachmentOut:
    return AttachmentOut(
        id=attachment.id,
        filename=attachment.filename,
        content_type=attachment.content_type,
        size_bytes=attachment.size_bytes,
        inline=attachment.inline_allowed,
        uploaded_by=page_repo.author_name(db, attachment.uploaded_by),
        created_at=attachment.created_at,
        url=f"/api/v1/attachments/{attachment.id}",
    )


@router.get("/spaces/{space}/pages/{page_id}/attachments", dependencies=[Depends(space_viewer)])
def list_attachments(page_id: PageId, current: CurrentSpace, db: Db) -> list[AttachmentOut]:
    page = live_page(db, current, page_id)
    return [_out(db, a) for a in page_repo.attachments(db, page.id)]


async def _read_limited(upload: UploadFile, limit: int) -> bytes:
    chunks: list[bytes] = []
    size = 0
    while chunk := await upload.read(UPLOAD_CHUNK):
        size += len(chunk)
        if size > limit:
            raise AppError(
                413, "PAYLOAD_TOO_LARGE", f"Files are limited to {limit // (1024 * 1024)} MB"
            )
        chunks.append(chunk)
    return b"".join(chunks)


@router.post(
    "/spaces/{space}/pages/{page_id}/attachments",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(space_editor)],
)
async def upload_attachment(
    page_id: PageId,
    file: Annotated[UploadFile, File()],
    current: CurrentSpace,
    db: Db,
    ctx: Ctx,
    actor: CurrentActor,
) -> AttachmentOut:
    page = live_page(db, current, page_id)
    data = await _read_limited(file, ctx.settings.max_attachment_bytes)
    attachment = attachment_service.store(
        db,
        ctx.settings.attachments_dir,
        page,
        current.principal.user.id,
        file.filename or "file",
        data,
    )
    audit_service.record(
        db,
        actor,
        "attachment.uploaded",
        target_type="attachment",
        target_id=attachment.id,
        after={"page": str(page.id), "filename": attachment.filename, "sha256": attachment.sha256},
    )
    db.commit()
    return _out(db, attachment)


def _authorized(
    db: Db, principal: Principal, attachment_id: uuid.UUID, min_role: str
) -> tuple[Attachment, Page]:
    """The attachment's page must be live and readable; unreadable means not found."""
    attachment = db.get(Attachment, attachment_id)
    page = db.get(Page, attachment.page_id) if attachment else None
    space = page_repo.space_of(db, page) if page else None
    role = space_repo.role_in_space(db, principal.user.id, space) if space else None
    if attachment is None or page is None or page.deleted_at is not None or role is None:
        raise AppError(404, "NOT_FOUND", "Not found")
    if ROLE_RANK[role] < ROLE_RANK[min_role]:
        raise AppError(403, "FORBIDDEN", "You do not have permission to do this")
    if min_role != "viewer" and space is not None and space.archived_at is not None:
        raise AppError(409, "SPACE_ARCHIVED", "This space is archived and read-only")
    return attachment, page


def _disposition(attachment: Attachment) -> str:
    kind = "inline" if attachment.inline_allowed else "attachment"
    ascii_name = attachment.filename.encode("ascii", "replace").decode().replace('"', "_")
    return f"{kind}; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(attachment.filename)}"


@router.get("/attachments/{attachment_id}", dependencies=[Depends(authenticated)])
def download(
    attachment_id: uuid.UUID, principal: CurrentPrincipal, db: Db, ctx: Ctx
) -> FileResponse:
    attachment, _ = _authorized(db, principal, attachment_id, "viewer")
    return FileResponse(
        attachment_service.path_of(ctx.settings.attachments_dir, attachment),
        media_type=attachment.content_type,
        headers={
            "Content-Disposition": _disposition(attachment),
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": ATTACHMENT_CSP,
        },
    )


@router.delete(
    "/attachments/{attachment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(authenticated)],
)
def delete_attachment(
    attachment_id: uuid.UUID, principal: CurrentPrincipal, db: Db, ctx: Ctx, actor: CurrentActor
) -> None:
    attachment, page = _authorized(db, principal, attachment_id, "editor")
    db.delete(attachment)
    db.flush()
    attachment_service.remove_file(ctx.settings.attachments_dir, attachment)
    audit_service.record(
        db,
        actor,
        "attachment.deleted",
        target_type="attachment",
        target_id=attachment.id,
        before={"page": str(page.id), "filename": attachment.filename},
    )
    db.commit()
