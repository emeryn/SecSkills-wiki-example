"""Application factory."""

import logging
import re
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import Engine

from app.api import mcp
from app.api.v1 import api_router
from app.core.config import Settings, get_settings
from app.core.context import build_context
from app.core.csrf import CsrfMiddleware
from app.core.db import create_db_engine
from app.core.errors import install_error_handlers
from app.core.idempotency import IdempotencyMiddleware
from app.core.ip_blocklist import BlockedIpMiddleware
from app.core.logging import configure_logging
from app.core.middleware import BodySizeLimitMiddleware, RequestContextMiddleware
from app.core.permissions import route_policies
from app.core.sandbox import install_exec_filter
from app.core.secrets import SecretsProvider, build_secrets_provider
from app.services import log_forwarding, server_errors

logger = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    engine: Engine | None = None,
    secrets: SecretsProvider | None = None,
) -> FastAPI:
    """Build the ASGI application. ``engine`` and ``secrets`` are injectable for tests."""
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    secrets = secrets or build_secrets_provider(settings)
    if engine is None:
        engine = create_db_engine(settings, secrets, role="runtime")
    context = build_context(settings, engine, secrets)
    log_forwarding.install(context, "backend")

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if settings.sandbox_enabled:
            install_exec_filter()
        stop = threading.Event()
        # Tests reload settings synchronously; a background thread would outlive their database.
        if settings.environment != "test":
            context.runtime.refresh()
            context.runtime.run_refresher(stop)
        logger.info("Backend started", extra={"environment": settings.environment})
        yield
        stop.set()
        engine.dispose()

    docs_url = "/api/v1/openapi.json" if settings.api_docs_enabled else None
    app = FastAPI(
        title="Wiki API",
        version="0.1.0",
        openapi_url=docs_url,
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.context = context

    install_error_handlers(app)
    app.include_router(api_router)
    app.include_router(mcp.router)
    route_policies(app)
    # Last added runs first: context → size limit → blocked IPs → CSRF → idempotency → routes.
    app.add_middleware(IdempotencyMiddleware, sessions=context.sessions)
    app.add_middleware(
        CsrfMiddleware, csrf_key=context.csrf_key, public_origin=settings.public_origin
    )
    app.add_middleware(BlockedIpMiddleware, blocklist=context.blocklist)
    upload_path = re.compile(r"^/api/v1/spaces/[a-z0-9-]+/pages/[0-9a-f-]+/attachments$")
    app.add_middleware(
        BodySizeLimitMiddleware,
        max_bytes=settings.max_request_body_bytes,
        # Multipart envelope around the file: allow a little more than the file limit.
        overrides=[(upload_path, settings.max_attachment_bytes + 64 * 1024)],
    )
    app.add_middleware(
        RequestContextMiddleware,
        trusted_proxy_count=settings.trusted_proxy_count,
        on_server_error=server_errors.request_hook(context),
    )
    return app
