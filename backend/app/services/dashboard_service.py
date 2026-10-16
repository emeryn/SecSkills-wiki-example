"""Administration dashboard: usage, errors, security alerts and backups over a period."""

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditEvent
from app.repositories import stats
from app.schemas.audit import AuditActor, AuditEventOut
from app.schemas.dashboard import (
    ActivityPoint,
    BackupStatus,
    ContentStats,
    DashboardOut,
    ErrorStats,
    Period,
    SecurityStats,
    ServerErrorOut,
    UserStats,
)

PERIODS: dict[str, tuple[timedelta, stats.Bucket]] = {
    "24h": (timedelta(hours=24), "hour"),
    "7d": (timedelta(days=7), "day"),
    "30d": (timedelta(days=30), "day"),
}
HONEYTOKEN_ACTION = "security.honeytoken"
BACKUP_OVERDUE_AFTER = timedelta(hours=26)
BACKUP_ACTION = "backup.created"


def event_out(event: AuditEvent, username: str | None) -> AuditEventOut:
    return AuditEventOut(
        id=event.id,
        occurred_at=event.occurred_at,
        actor=AuditActor(id=event.actor_user_id, username=username),
        actor_ip=str(event.actor_ip) if event.actor_ip else None,
        user_agent=event.user_agent,
        action=event.action,
        outcome=event.outcome,
        severity=event.severity,
        target_type=event.target_type,
        target_id=event.target_id,
        before=event.before,
        after=event.after,
        request_id=event.request_id,
    )


def _buckets(since: datetime, now: datetime, bucket: stats.Bucket) -> list[datetime]:
    step = timedelta(hours=1) if bucket == "hour" else timedelta(days=1)
    start = since.replace(minute=0, second=0, microsecond=0)
    if bucket == "day":
        start = start.replace(hour=0)
    slots = []
    while start <= now:
        slots.append(start)
        start += step
    return slots


def _activity(db: Session, since: datetime, now: datetime, bucket: stats.Bucket) -> list[Any]:
    sign_ins, edits = stats.activity(db, since, bucket)
    points = []
    for slot in _buckets(since, now, bucket):
        naive = slot.replace(tzinfo=None)
        points.append(
            ActivityPoint(bucket=slot, sign_ins=sign_ins.get(naive, 0), edits=edits.get(naive, 0))
        )
    return points


def _backup(db: Session, now: datetime) -> BackupStatus:
    latest = stats.latest_audit(db, BACKUP_ACTION, 1)
    if not latest:
        return BackupStatus(last_at=None, size_bytes=None, overdue=True)
    event = latest[0][0]
    size = (event.after or {}).get("size_bytes")
    return BackupStatus(
        last_at=event.occurred_at,
        size_bytes=int(size) if size else None,
        overdue=now - event.occurred_at > BACKUP_OVERDUE_AFTER,
    )


def dashboard(db: Session, period: Period) -> DashboardOut:
    now = datetime.now(UTC)
    length, bucket = PERIODS[period]
    since = now - length
    error_count, recent_errors = stats.server_errors(db, since, 10)
    return DashboardOut(
        period=period,
        since=since,
        users=UserStats(**stats.users(db, since)),
        content=ContentStats(**stats.content(db, since)),
        security=SecurityStats(
            failed_sign_ins=stats.audit_count(db, "auth.login", since, outcome="failure"),
            honeytoken_alerts=stats.audit_count(db, HONEYTOKEN_ACTION, since),
            blocked_ips=stats.blocked_ips(db, now),
        ),
        errors=ErrorStats(
            count=error_count,
            recent=[
                ServerErrorOut(
                    id=e.id,
                    occurred_at=e.occurred_at,
                    source=e.source,
                    method=e.method,
                    path=e.path,
                    status=e.status,
                    request_id=e.request_id,
                )
                for e in recent_errors
            ],
        ),
        backup=_backup(db, now),
        activity=_activity(db, since, now, bucket),
        alerts=[event_out(e, u) for e, u in stats.latest_audit(db, HONEYTOKEN_ACTION, 5, since)],
    )
