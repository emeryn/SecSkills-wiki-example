"""MCP endpoints (Streamable HTTP): ``/mcp`` for users, ``/mcp/admin`` for administrators.

No cookies: clients present ``Authorization: Bearer wk_…``. ``Origin``, when sent, must be the
wiki's own (DNS rebinding protection). Each key is rate limited. The admin endpoint is off by
default and needs an admin-scoped key of an active administrator.
"""

import json
from typing import Any, Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from app.api.deps import Ctx, Db, api_key
from app.core.context import AppContext
from app.core.errors import AppError, error_body
from app.core.logging import request_id_var
from app.core.rate_limit import RateLimiter
from app.mcp import admin_tools, tools
from app.mcp.server import SUPPORTED_VERSIONS, ToolContext, handle
from app.models import ApiKey, User
from app.services import api_key_service
from app.services.audit_service import Actor

router = APIRouter(prefix="/mcp", tags=["mcp"])

Endpoint = Literal["user", "admin"]
_limiters: dict[int, RateLimiter] = {}


def _error(
    status: int, code: str, message: str, headers: dict[str, str] | None = None
) -> JSONResponse:
    return JSONResponse(error_body(code, message), status_code=status, headers=headers)


def _authenticate(
    request: Request, db: Db, ctx: AppContext, endpoint: Endpoint
) -> tuple[ApiKey, User]:
    origin = request.headers.get("origin")
    if origin is not None and origin != ctx.settings.public_origin:
        raise AppError(403, "ORIGIN_REFUSED", "Requests from this origin are refused")
    header = request.headers.get("authorization", "")
    scheme, _, secret = header.partition(" ")
    found = (
        api_key_service.authenticate(db, secret.strip(), request.scope["state"].get("client_ip"))
        if scheme.lower() == "bearer"
        else None
    )
    if found is None:
        raise AppError(401, "UNAUTHENTICATED", "A valid API key is required")
    key, user = found
    settings = ctx.runtime.snapshot().mcp
    if not (settings.admin_enabled if endpoint == "admin" else settings.user_enabled):
        raise AppError(404, "NOT_FOUND", "Not found")
    if endpoint == "admin" and ("admin" not in key.scopes or user.global_role != "admin"):
        raise AppError(403, "FORBIDDEN", "An administrator key with the admin scope is required")
    limiter = _limiters.setdefault(
        settings.requests_per_minute, RateLimiter(settings.requests_per_minute, 60)
    )
    limiter.check(str(key.id))
    return key, user


def _actor(request: Request, user: User) -> Actor:
    state = request.scope["state"]
    return Actor(
        user_id=user.id,
        ip=state.get("client_ip"),
        user_agent=request.headers.get("user-agent", "")[:512],
        request_id=request_id_var.get(),
        ip_trusted=bool(state.get("client_ip_trusted")),
    )


def _process(
    request: Request, body: bytes, db: Db, ctx: AppContext, endpoint: Endpoint
) -> Response:
    try:
        key, user = _authenticate(request, db, ctx, endpoint)
    except AppError as exc:
        unauthenticated = exc.code == "UNAUTHENTICATED"
        headers = {"WWW-Authenticate": 'Bearer realm="wiki"'} if unauthenticated else None
        return _error(exc.status_code, exc.code, exc.message, headers)
    version = request.headers.get("mcp-protocol-version")
    if version is not None and version not in SUPPORTED_VERSIONS:
        return _error(400, "UNSUPPORTED_PROTOCOL_VERSION", "Unsupported MCP protocol version")
    try:
        message: Any = json.loads(body)
    except ValueError:
        return JSONResponse(
            {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
        )
    registry = admin_tools.ADMIN_TOOLS if endpoint == "admin" else tools.USER_TOOLS
    instructions = admin_tools.INSTRUCTIONS if endpoint == "admin" else tools.INSTRUCTIONS
    context = ToolContext(db=db, ctx=ctx, user=user, key=key, actor=_actor(request, user))
    response = handle(message, registry, context, endpoint, instructions)
    if response is None:
        return Response(status_code=202)
    return JSONResponse(response)


async def _serve(request: Request, db: Db, ctx: AppContext, endpoint: Endpoint) -> Response:
    body = await request.body()
    return await run_in_threadpool(_process, request, body, db, ctx, endpoint)


def _no_stream(request: Request, db: Db, ctx: AppContext, endpoint: Endpoint) -> Response:
    """No server-initiated stream (stateless server); authentication is still checked first."""
    try:
        _authenticate(request, db, ctx, endpoint)
    except AppError as exc:
        return _error(exc.status_code, exc.code, exc.message)
    return Response(status_code=405, headers={"Allow": "POST"})


@router.post("", dependencies=[Depends(api_key)])
async def user_endpoint(request: Request, db: Db, ctx: Ctx) -> Response:
    return await _serve(request, db, ctx, "user")


@router.post("/admin", dependencies=[Depends(api_key)])
async def admin_endpoint(request: Request, db: Db, ctx: Ctx) -> Response:
    return await _serve(request, db, ctx, "admin")


@router.get("", dependencies=[Depends(api_key)])
def user_stream(request: Request, db: Db, ctx: Ctx) -> Response:
    return _no_stream(request, db, ctx, "user")


@router.get("/admin", dependencies=[Depends(api_key)])
def admin_stream(request: Request, db: Db, ctx: Ctx) -> Response:
    return _no_stream(request, db, ctx, "admin")
