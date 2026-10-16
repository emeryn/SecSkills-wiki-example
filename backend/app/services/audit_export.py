"""Audit trail CSV export, safe to open in a spreadsheet, and itself audited."""

import csv
import io
import json
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import AuditEvent
from app.repositories import audit as audit_repo
from app.schemas.audit import AuditFilters
from app.services import audit_service
from app.services.audit_service import Actor

EXPORT_LIMIT = 50_000
COLUMNS = (
    "id",
    "occurred_at",
    "actor_username",
    "actor_user_id",
    "actor_ip",
    "user_agent",
    "action",
    "outcome",
    "severity",
    "target_type",
    "target_id",
    "request_id",
    "before",
    "after",
)
# Spreadsheets evaluate cells starting with these characters as formulas.
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def escape_cell(value: object) -> str:
    """Text of a cell; anything a spreadsheet could read as a formula is prefixed with ``'``."""
    if value is None:
        return ""
    if isinstance(value, dict | list):
        text = json.dumps(value, sort_keys=True, default=str)
    elif isinstance(value, datetime):
        text = value.astimezone(UTC).isoformat()
    else:
        text = str(value)
    return "'" + text if text.startswith(FORMULA_PREFIXES) else text


def _row(event: AuditEvent, username: str | None) -> list[str]:
    values: list[Any] = [
        event.id,
        event.occurred_at,
        username,
        event.actor_user_id,
        event.actor_ip,
        event.user_agent,
        event.action,
        event.outcome,
        event.severity,
        event.target_type,
        event.target_id,
        event.request_id,
        event.before,
        event.after,
    ]
    return [escape_cell(value) for value in values]


def to_csv(rows: Iterable[tuple[AuditEvent, str | None]]) -> str:
    buffer = io.StringIO()
    # The BOM makes spreadsheets read the file as UTF-8.
    buffer.write("﻿")
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(COLUMNS)
    for event, username in rows:
        writer.writerow(_row(event, username))
    return buffer.getvalue()


def export(db: Session, filters: AuditFilters, actor: Actor) -> tuple[str, str]:
    """Return ``(filename, csv)``; the export itself is recorded with its filters and size."""
    total = audit_repo.count(db, filters)
    if total > EXPORT_LIMIT:
        raise AppError(
            422,
            "EXPORT_TOO_LARGE",
            f"{total} events match; narrow the filters to {EXPORT_LIMIT} or fewer",
        )
    content = to_csv(audit_repo.iterate(db, filters))
    audit_service.record(
        db,
        actor,
        "audit.exported",
        target_type="audit",
        after={"filters": filters.as_dict(), "rows": total},
    )
    db.commit()
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return f"audit-{stamp}.csv", content
