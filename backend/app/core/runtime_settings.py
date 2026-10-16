"""Settings sections stored encrypted in the database, cached per process.

Each section is one ``settings`` row: JSON encrypted under its own data key, bound to the row by
the AEAD context. A section that fails to decrypt or validate falls back to its defaults (logged),
so a damaged row never prevents the application from starting.
"""

import json
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, cast

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.crypto import FieldCipher
from app.models import Setting
from app.schemas.settings import (
    SECTION_MODELS,
    LdapSettings,
    LlmSettings,
    McpSettings,
    NotificationSettings,
    OidcSettings,
    PrivacySettings,
    SecuritySettings,
    SmtpSettings,
    SyslogSettings,
    WebhookSettings,
)

logger = logging.getLogger(__name__)

REFRESH_SECONDS = 15.0


def value_context(key: str) -> str:
    return f"settings.value:{key}"


def decrypt_section(cipher: FieldCipher, row: Setting) -> dict[str, Any]:
    dek = cipher.unwrap(row.dek_wrapped)
    data = json.loads(cipher.decrypt(dek, row.value_enc, value_context(row.key)))
    if not isinstance(data, dict):
        raise TypeError("Settings value is not an object")
    return cast(dict[str, Any], data)


def encrypt_section(cipher: FieldCipher, row: Setting, values: dict[str, Any]) -> None:
    dek, wrapped = cipher.new_data_key()
    row.dek_wrapped = wrapped
    row.key_version = cipher.key_version
    row.value_enc = cipher.encrypt(dek, json.dumps(values), value_context(row.key))


@dataclass(frozen=True)
class Snapshot:
    """Every section, validated; defaults where nothing is stored."""

    syslog: SyslogSettings = field(default_factory=SyslogSettings)
    smtp: SmtpSettings = field(default_factory=SmtpSettings)
    webhook: WebhookSettings = field(default_factory=WebhookSettings)
    notifications: NotificationSettings = field(default_factory=NotificationSettings)
    privacy: PrivacySettings = field(default_factory=PrivacySettings)
    security: SecuritySettings = field(default_factory=SecuritySettings)
    # Stored values only: environment variables are applied by ``services.sso_config``.
    oidc: OidcSettings = field(default_factory=OidcSettings)
    ldap: LdapSettings = field(default_factory=LdapSettings)
    llm: LlmSettings = field(default_factory=LlmSettings)
    mcp: McpSettings = field(default_factory=McpSettings)


def load_snapshot(db: Session, cipher: FieldCipher) -> Snapshot:
    sections: dict[str, Any] = {}
    for row in db.scalars(select(Setting)).all():
        model = SECTION_MODELS.get(row.key)
        if model is None:
            continue
        try:
            sections[row.key] = model.model_validate(decrypt_section(cipher, row))
        except ValueError, TypeError, ValidationError:
            logger.error("Stored settings are invalid; defaults apply", extra={"section": row.key})
    return Snapshot(**sections)


Listener = Callable[[Snapshot], None]


class RuntimeSettings:
    """Process-wide cache. ``snapshot()`` reloads when stale; ``current()`` never touches the DB."""

    def __init__(self, sessions: sessionmaker[Session], cipher: FieldCipher) -> None:
        self._sessions = sessions
        self._cipher = cipher
        self._lock = threading.Lock()
        self._snapshot = Snapshot()
        self._loaded_at = float("-inf")
        self._listeners: list[Listener] = []

    def subscribe(self, listener: Listener) -> None:
        """Call ``listener`` now and after every reload (log masking, syslog, notifications)."""
        self._listeners.append(listener)
        listener(self._snapshot)

    def current(self) -> Snapshot:
        return self._snapshot

    def snapshot(self) -> Snapshot:
        if time.monotonic() - self._loaded_at >= REFRESH_SECONDS:
            self.refresh()
        return self._snapshot

    def refresh(self) -> Snapshot:
        try:
            with self._sessions() as db:
                loaded = load_snapshot(db, self._cipher)
        except Exception:
            logger.warning("Settings could not be reloaded; keeping the previous values")
            return self._snapshot
        with self._lock:
            changed = loaded != self._snapshot
            self._snapshot = loaded
            self._loaded_at = time.monotonic()
        if changed:
            for listener in self._listeners:
                listener(loaded)
        return loaded

    def run_refresher(self, stop: threading.Event) -> threading.Thread:
        """Reload periodically in a daemon thread until ``stop`` is set."""

        def loop() -> None:
            while not stop.wait(REFRESH_SECONDS):
                self.refresh()

        thread = threading.Thread(target=loop, name="settings-refresher", daemon=True)
        thread.start()
        return thread
