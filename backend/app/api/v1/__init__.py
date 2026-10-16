"""Version 1 of the API, mounted under ``/api/v1``."""

from fastapi import APIRouter

from app.api.v1 import (
    api_keys,
    ask,
    attachments,
    auth,
    export,
    feed,
    health,
    me,
    pages,
    revisions,
    search,
    spaces,
    sso,
    trap,
    trash,
)
from app.api.v1.admin import admin_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(sso.router)
api_router.include_router(me.router)
api_router.include_router(spaces.router)
api_router.include_router(pages.router)
api_router.include_router(revisions.router)
api_router.include_router(trash.router)
api_router.include_router(feed.router)
api_router.include_router(search.router)
api_router.include_router(attachments.router)
api_router.include_router(export.router)
api_router.include_router(ask.router)
api_router.include_router(api_keys.router)
api_router.include_router(trap.router)
api_router.include_router(admin_router)
