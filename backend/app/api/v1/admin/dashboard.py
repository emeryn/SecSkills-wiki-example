"""Administration dashboard."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import Db, require
from app.core.permissions import Permission
from app.schemas.dashboard import DashboardOut, DashboardParams
from app.services import dashboard_service

router = APIRouter(prefix="/dashboard", tags=["admin"])


@router.get("", dependencies=[Depends(require(Permission.DASHBOARD_READ))])
def get_dashboard(params: Annotated[DashboardParams, Query()], db: Db) -> DashboardOut:
    return dashboard_service.dashboard(db, params.period)
