"""Server errors shown on the administration dashboard: method, path and request id only."""

import logging
from collections.abc import Callable
from datetime import UTC, datetime

from app.core.context import AppContext
from app.models import ServerError

logger = logging.getLogger(__name__)


def record(
    ctx: AppContext, source: str, method: str, path: str, status: int, request_id: str | None
) -> None:
    with ctx.sessions() as db:
        db.add(
            ServerError(
                occurred_at=datetime.now(UTC),
                source=source,
                method=method[:16],
                path=path[:300],
                status=status,
                request_id=request_id,
            )
        )
        db.commit()


def request_hook(ctx: AppContext) -> Callable[[str, str, int, str], None]:
    """Hook for ``RequestContextMiddleware``: one row per 5xx response."""

    def hook(method: str, path: str, status: int, request_id: str) -> None:
        record(ctx, "request", method, path, status, request_id)

    return hook


def record_job_failure(ctx: AppContext, job: str) -> None:
    try:
        record(ctx, "job", "JOB", job, 500, None)
    except Exception:
        logger.warning("Job failure could not be recorded", extra={"job": job})
