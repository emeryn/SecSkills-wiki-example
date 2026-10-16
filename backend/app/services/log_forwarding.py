"""Attaches remote syslog, notifications and PII masking to the process's logging."""

import logging

from app.core.context import AppContext
from app.core.logging import set_pii_masking
from app.core.runtime_settings import Snapshot
from app.services.notifier import Notifier
from app.services.syslog_forwarder import SyslogForwarder


def _apply_privacy(snapshot: Snapshot) -> None:
    set_pii_masking(snapshot.privacy.mask_pii)


def install(ctx: AppContext, procid: str) -> None:
    """Call after ``configure_logging``; handlers follow every settings reload.

    Tests never forward: a saved test destination must not receive real connections.
    """
    ctx.runtime.subscribe(_apply_privacy)
    if ctx.settings.environment == "test":
        return
    syslog = SyslogForwarder(ctx.settings.public_hostname, procid)
    notifier = Notifier(ctx.runtime, ctx.mailer)
    root = logging.getLogger()
    root.addHandler(syslog)
    root.addHandler(notifier)
    ctx.runtime.subscribe(syslog.configure)
