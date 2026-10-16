"""Honeytoken endpoint: referenced nowhere, so only scanners and attackers request it.

Nginx also routes classic probe paths (``/.env``, ``/.git/``…) here. The answer is the generic 404
every unknown path gets, so the trap is not recognizable.
"""

from fastapi import APIRouter, Depends, Request

from app.api.deps import Ctx, CurrentActor, Db, public
from app.core.errors import AppError
from app.services import honeytoken_service

router = APIRouter(tags=["internal"])


@router.get("/debug/config", dependencies=[Depends(public)], include_in_schema=False)
def trap(request: Request, db: Db, ctx: Ctx, actor: CurrentActor) -> None:
    if ctx.runtime.snapshot().security.honeytokens_enabled:
        probe = request.headers.get("x-original-uri", request.url.path)[:200]
        honeytoken_service.trigger(db, ctx, actor, "trap_endpoint", {"path": probe})
        db.commit()
    raise AppError(404, "NOT_FOUND", "Not found")
