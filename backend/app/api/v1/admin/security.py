"""Blocked client IPs (honeytoken hits)."""

from fastapi import APIRouter, Depends, status

from app.api.deps import Ctx, CurrentActor, Db, require
from app.core.permissions import Permission
from app.schemas.audit import BlockedIpOut
from app.services import honeytoken_service

router = APIRouter(prefix="/blocked-ips", tags=["admin"])

manage = require(Permission.SECURITY_MANAGE)


@router.get("", dependencies=[Depends(manage)])
def list_blocked(db: Db) -> list[BlockedIpOut]:
    return [
        BlockedIpOut(
            ip=str(row.ip),
            reason=row.reason,
            hits=row.hits,
            blocked_at=row.blocked_at,
            expires_at=row.expires_at,
        )
        for row in honeytoken_service.list_blocked(db)
    ]


@router.delete("/{ip}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(manage)])
def unblock(ip: str, db: Db, ctx: Ctx, actor: CurrentActor) -> None:
    honeytoken_service.unblock(db, ctx, ip, actor)
