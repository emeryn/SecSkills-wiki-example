"""Administration dashboard schemas."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.schemas.audit import AuditEventOut
from app.schemas.common import StrictModel

Period = Literal["24h", "7d", "30d"]


class DashboardParams(StrictModel):
    period: Period = "7d"


class UserStats(BaseModel):
    total: int
    active: int
    disabled: int
    signed_in: int


class ContentStats(BaseModel):
    spaces: int
    pages: int
    revisions: int
    attachments: int
    attachment_bytes: int


class SecurityStats(BaseModel):
    failed_sign_ins: int
    honeytoken_alerts: int
    blocked_ips: int


class ServerErrorOut(BaseModel):
    id: int
    occurred_at: datetime
    source: str
    method: str
    path: str
    status: int
    request_id: str | None


class ErrorStats(BaseModel):
    count: int
    recent: list[ServerErrorOut]


class BackupStatus(BaseModel):
    last_at: datetime | None
    size_bytes: int | None
    # No backup, or the last one is older than a day plus a margin.
    overdue: bool


class ActivityPoint(BaseModel):
    bucket: datetime
    sign_ins: int
    edits: int


class DashboardOut(BaseModel):
    period: Period
    since: datetime
    users: UserStats
    content: ContentStats
    security: SecurityStats
    errors: ErrorStats
    backup: BackupStatus
    activity: list[ActivityPoint]
    alerts: list[AuditEventOut]
