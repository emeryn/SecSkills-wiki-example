"""Markdown export (zip) of a page subtree or a whole space."""

import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from fastapi.responses import FileResponse

from app.api.deps import Ctx, CurrentActor, Db
from app.api.space_access import CurrentSpace, space_viewer
from app.api.v1.pages import live_page
from app.core.errors import AppError
from app.repositories import throttle
from app.services import audit_service, export_service, session_service

router = APIRouter(tags=["export"])

EXPORTS_PER_USER_BEFORE_DELAY = 20


@router.get("/spaces/{space}/export", dependencies=[Depends(space_viewer)])
def export(
    current: CurrentSpace,
    db: Db,
    ctx: Ctx,
    actor: CurrentActor,
    background: BackgroundTasks,
    page: Annotated[uuid.UUID | None, Query()] = None,
) -> FileResponse:
    """Whole space (needs a recent identity confirmation) or ``?page=`` with its sub-pages."""
    user_id = current.principal.user.id
    root = live_page(db, current, page) if page is not None else None
    if root is None and not session_service.recently_authenticated(ctx, current.principal.session):
        raise AppError(401, "REAUTH_REQUIRED", "Confirm your identity to continue")
    subject = f"export:{user_id}"
    now = datetime.now(UTC)
    wait = throttle.retry_after(db, [subject], now)
    if wait > 0:
        raise AppError(429, "RATE_LIMITED", f"Too many exports. Try again in {wait} seconds")
    throttle.register_failure(db, subject, EXPORTS_PER_USER_BEFORE_DELAY, now)

    archive = export_service.build_archive(db, ctx.settings.attachments_dir, current.space, root)
    audit_service.record(
        db,
        actor,
        "space.exported" if root is None else "page.exported",
        target_type="space" if root is None else "page",
        target_id=current.space.id if root is None else root.id,
        after={"space": current.space.key},
    )
    db.commit()
    background.add_task(Path(archive).unlink, missing_ok=True)
    name = f"{current.space.key}{'-' + root.slug if root else ''}-{now:%Y%m%d}.zip"
    return FileResponse(
        archive,
        media_type="application/zip",
        filename=name,
        headers={"X-Content-Type-Options": "nosniff"},
    )
