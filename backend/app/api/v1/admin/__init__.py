"""Administration API under ``/api/v1/admin``; every route requires an admin permission."""

from fastapi import APIRouter

from app.api.v1.admin import audit, dashboard, groups, llm, security, settings, spaces, users

admin_router = APIRouter(prefix="/admin")
admin_router.include_router(users.router)
admin_router.include_router(groups.router)
admin_router.include_router(spaces.router)
admin_router.include_router(dashboard.router)
admin_router.include_router(audit.router)
admin_router.include_router(settings.router)
admin_router.include_router(security.router)
admin_router.include_router(llm.router)
