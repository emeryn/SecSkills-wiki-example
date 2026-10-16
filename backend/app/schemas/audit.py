"""Audit viewer and blocked IP schemas."""

import ipaddress
import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import PageParams, StrictModel

Outcome = Literal["success", "failure"]
Severity = Literal["info", "warning", "critical"]


class AuditFilters(StrictModel):
    """``action`` matches exactly, or as a prefix when it ends with a dot (``auth.``)."""

    action: str | None = Field(None, max_length=64, pattern=r"^[a-z_]+(\.[a-z_]*)*$")
    # A username, or ``system`` for scheduled jobs and the CLI.
    actor: str | None = Field(None, max_length=64, pattern=r"^[A-Za-z0-9._-]+$")
    outcome: Outcome | None = None
    severity: Severity | None = None
    target_type: str | None = Field(None, max_length=32, pattern=r"^[a-z_]+$")
    target_id: str | None = Field(None, max_length=64, pattern=r"^[A-Za-z0-9._:-]+$")
    ip: str | None = Field(None, max_length=45, pattern=r"^[0-9A-Fa-f:.]+$")
    start: datetime | None = None
    end: datetime | None = None

    @field_validator("ip")
    @classmethod
    def _ip(cls, value: str | None) -> str | None:
        return str(ipaddress.ip_address(value)) if value else None

    def as_dict(self) -> dict[str, str]:
        """Non-empty filters, as recorded in the export audit event."""
        return {
            name: value.isoformat() if isinstance(value, datetime) else str(value)
            for name, value in self.model_dump().items()
            if name in AuditFilters.model_fields and value is not None
        }


class AuditListParams(AuditFilters, PageParams):
    pass


class AuditActor(BaseModel):
    id: uuid.UUID | None
    username: str | None


class AuditEventOut(BaseModel):
    id: int
    occurred_at: datetime
    actor: AuditActor
    actor_ip: str | None
    user_agent: str
    action: str
    outcome: str
    severity: str
    target_type: str | None
    target_id: str | None
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    request_id: str | None


class BlockedIpOut(BaseModel):
    ip: str
    reason: str
    hits: int
    blocked_at: datetime
    expires_at: datetime | None
