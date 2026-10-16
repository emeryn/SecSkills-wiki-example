"""Scheduled hygiene: expired sessions, tokens, idempotency keys, throttling, IP blocks, trash."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import delete, or_
from sqlalchemy.orm import Session

from app.models import (
    AuthSession,
    AuthThrottle,
    BlockedIp,
    IdempotencyKey,
    OidcFlow,
    PasswordResetToken,
    ServerError,
)
from app.services import attachment_service, trash_service

RETENTION = timedelta(days=1)
THROTTLE_RETENTION = timedelta(hours=24)
SERVER_ERROR_RETENTION = timedelta(days=90)


def purge_expired(db: Session, attachments_dir: Path | None = None) -> dict[str, int]:
    now = datetime.now(UTC)
    cutoff = now - RETENTION
    statements = {
        "sessions": delete(AuthSession).where(
            or_(
                AuthSession.revoked_at < cutoff,
                AuthSession.idle_expires_at < cutoff,
                AuthSession.absolute_expires_at < cutoff,
            )
        ),
        "reset_tokens": delete(PasswordResetToken).where(
            or_(PasswordResetToken.expires_at < cutoff, PasswordResetToken.used_at < cutoff)
        ),
        "idempotency_keys": delete(IdempotencyKey).where(IdempotencyKey.expires_at < now),
        "throttle": delete(AuthThrottle).where(
            AuthThrottle.last_failure_at < now - THROTTLE_RETENTION
        ),
        "blocked_ips": delete(BlockedIp).where(BlockedIp.expires_at < now),
        "oidc_flows": delete(OidcFlow).where(OidcFlow.expires_at < now),
        "server_errors": delete(ServerError).where(
            ServerError.occurred_at < now - SERVER_ERROR_RETENTION
        ),
    }
    counts = {
        name: int(getattr(db.execute(stmt), "rowcount", 0) or 0)
        for name, stmt in statements.items()
    }
    db.commit()
    counts["trashed_pages"] = trash_service.purge_expired(db)
    if attachments_dir is not None:
        counts["orphaned_files"] = attachment_service.purge_orphans(db, attachments_dir)
    return counts
