"""Liveness and readiness."""

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.api.deps import Ctx, public
from app.core.db import database_is_available
from app.core.errors import error_body

router = APIRouter(tags=["health"])


@router.get("/health", dependencies=[Depends(public)])
def health(ctx: Ctx) -> JSONResponse:
    """Report whether the API can reach the database. Never exposes failure details."""
    if not database_is_available(ctx.engine):
        return JSONResponse(
            error_body("DATABASE_UNAVAILABLE", "Service unavailable"), status_code=503
        )
    return JSONResponse({"status": "ok"})
