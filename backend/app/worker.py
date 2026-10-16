"""Scheduled jobs process (``worker`` service).

Jobs: hygiene (expired sessions, tokens, idempotency keys, throttling, IP blocks, trash purge,
orphaned files), dormant account disabling, encrypted backups, and the embeddings of new page
revisions for "Ask the wiki". A failed job is logged (which
notifies administrators when notifications are configured) and shown on the dashboard.
"""

import logging
import signal
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from app.core.config import get_settings
from app.core.context import AppContext, build_context
from app.core.crypto import decode_key
from app.core.db import create_db_engine
from app.core.logging import configure_logging
from app.core.sandbox import install_exec_filter
from app.core.secrets import SecretsProvider, build_secrets_provider
from app.services import (
    account_hygiene,
    backup_service,
    log_forwarding,
    maintenance,
    rag_indexer,
    server_errors,
)

logger = logging.getLogger("app.worker")

TICK_SECONDS = 30.0
EMBEDDING_INTERVAL_SECONDS = 30.0
DAY_SECONDS = 86400.0


@dataclass
class Job:
    name: str
    interval_seconds: float
    run: Callable[[], object]
    last_run: float = float("-inf")


def _jobs(ctx: AppContext, secrets: SecretsProvider) -> list[Job]:
    settings = ctx.settings

    def hygiene() -> object:
        with ctx.sessions() as db:
            return maintenance.purge_expired(db, settings.attachments_dir)

    def dormant_accounts() -> object:
        with ctx.sessions() as db:
            return account_hygiene.disable_inactive(db, settings.inactive_account_days)

    def backup() -> object:
        key = decode_key(secrets.read(backup_service.BACKUP_KEY_SECRET))
        with ctx.sessions() as db:
            info = backup_service.run_scheduled(
                db,
                ctx.engine,
                key,
                settings.backups_dir,
                settings.attachments_dir,
                settings.backup_retention_count,
            )
        return info.name

    def embeddings() -> object:
        with ctx.sessions() as db:
            return rag_indexer.index_pending(db, ctx)

    jobs = [
        Job("hygiene", settings.worker_interval_seconds, hygiene),
        Job("dormant-accounts", DAY_SECONDS, dormant_accounts),
        Job("embeddings", EMBEDDING_INTERVAL_SECONDS, embeddings),
    ]
    if settings.backup_interval_hours > 0:
        job = Job("backup", settings.backup_interval_hours * 3600.0, backup)
        latest = backup_service.list_backups(settings.backups_dir)
        if latest:
            # A restart must not take an extra backup: count from the newest file.
            age = time.time() - latest[0].created_at.timestamp()
            job.last_run = time.monotonic() - age
        jobs.append(job)
    return jobs


def run_due(ctx: AppContext, jobs: list[Job]) -> None:
    for job in jobs:
        if time.monotonic() - job.last_run < job.interval_seconds:
            continue
        job.last_run = time.monotonic()
        try:
            result = job.run()
            logger.info("Scheduled job done", extra={"job": job.name, "result": result})
        except Exception:
            logger.exception("Scheduled job failed", extra={"job": job.name})
            server_errors.record_job_failure(ctx, job.name)


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    if settings.sandbox_enabled:
        install_exec_filter()
    secrets = build_secrets_provider(settings)
    engine = create_db_engine(settings, secrets, role="runtime")
    ctx = build_context(settings, engine, secrets)
    log_forwarding.install(ctx, "worker")
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    ctx.runtime.refresh()
    ctx.runtime.run_refresher(stop)
    jobs = _jobs(ctx, secrets)
    logger.info("Worker started", extra={"jobs": [job.name for job in jobs]})
    while not stop.is_set():
        run_due(ctx, jobs)
        stop.wait(TICK_SECONDS)
    engine.dispose()
    logger.info("Worker stopped")


if __name__ == "__main__":
    main()
