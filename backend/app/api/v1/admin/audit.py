"""Audit trail viewer and CSV export."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response

from app.api.deps import CurrentActor, CurrentPrincipal, Db, require
from app.core.permissions import Permission
from app.core.rate_limit import RateLimiter
from app.repositories import audit as audit_repo
from app.schemas.audit import AuditEventOut, AuditFilters, AuditListParams
from app.schemas.common import Page
from app.services import audit_export
from app.services.dashboard_service import event_out

router = APIRouter(prefix="/audit", tags=["admin"])

read = require(Permission.AUDIT_READ)
export_recent = require(Permission.AUDIT_EXPORT, recent=True)
_export_limiter = RateLimiter(max_events=5, window_seconds=60)


@router.get("", dependencies=[Depends(read)])
def list_events(params: Annotated[AuditListParams, Query()], db: Db) -> Page[AuditEventOut]:
    rows, total = audit_repo.page(db, params, params.page, params.page_size)
    return Page(
        items=[event_out(event, username) for event, username in rows],
        total=total,
        page=params.page,
        page_size=params.page_size,
    )


@router.get("/actions", dependencies=[Depends(read)])
def list_actions(db: Db) -> list[str]:
    return audit_repo.distinct_actions(db)


@router.get("/export", dependencies=[Depends(export_recent)])
def export_events(
    filters: Annotated[AuditFilters, Query()],
    principal: CurrentPrincipal,
    db: Db,
    actor: CurrentActor,
) -> Response:
    _export_limiter.check(str(principal.user.id))
    filename, content = audit_export.export(db, filters, actor)
    return Response(
        content=content.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
