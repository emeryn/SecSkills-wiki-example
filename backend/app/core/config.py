"""Backend configuration, read once from ``BACKEND_*`` environment variables."""

from functools import cached_property, lru_cache
from pathlib import Path
from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class Settings(BaseSettings):
    """Validated settings. Secrets are never read from here: see ``core.secrets``."""

    model_config = SettingsConfigDict(env_prefix="BACKEND_", extra="forbid", frozen=True)

    environment: Literal["production", "development", "test"] = "production"
    log_level: LogLevel = "INFO"

    secrets_provider: Literal["file"] = "file"
    secrets_dir: Path = Path("/run/secrets")

    db_host: str = Field("db", max_length=253)
    db_port: int = Field(5432, ge=1, le=65535)
    db_pool_size: int = Field(5, ge=1, le=50)
    db_connect_timeout_seconds: int = Field(5, ge=1, le=60)

    trusted_proxy_count: int = Field(1, ge=0, le=5)
    max_request_body_bytes: int = Field(2 * 1024 * 1024, ge=1024, le=64 * 1024 * 1024)
    api_docs_enabled: bool = False
    sandbox_enabled: bool = True

    tls_hostnames: str = Field("localhost,127.0.0.1", max_length=1000)

    # Origin users reach the application at: CSRF origin check, WebAuthn, links in emails.
    public_url: str = Field("https://localhost:8443", max_length=2000)

    session_idle_minutes: int = Field(480, ge=5, le=1440)
    session_absolute_hours: int = Field(168, ge=1, le=720)
    admin_session_idle_minutes: int = Field(60, ge=5, le=60)
    admin_session_absolute_hours: int = Field(8, ge=1, le=8)
    pending_session_minutes: int = Field(10, ge=1, le=30)
    reauth_window_minutes: int = Field(5, ge=1, le=30)
    # "test" trades Argon2id cost for speed and is refused outside the test environment.
    password_hash_profile: Literal["rfc9106", "test"] = "rfc9106"  # noqa: S105

    smtp_host: str | None = Field(None, max_length=253)
    smtp_port: int = Field(465, ge=1, le=65535)
    smtp_from: str = Field("wiki@localhost", max_length=254)
    smtp_username: str | None = Field(None, max_length=254)
    smtp_password_file: Path | None = None
    smtp_ca_file: Path | None = None

    worker_interval_seconds: int = Field(600, ge=10, le=86400)
    # Accounts without a sign-in for this many days are disabled by the worker (0: never).
    inactive_account_days: int = Field(180, ge=0, le=3650)

    backups_dir: Path = Path("/var/lib/wiki/backups")
    # Encrypted backup every N hours (0: only on demand with `make backup`).
    backup_interval_hours: int = Field(24, ge=0, le=168)
    backup_retention_count: int = Field(14, ge=1, le=365)

    attachments_dir: Path = Path("/var/lib/wiki/attachments")
    max_attachment_bytes: int = Field(10 * 1024 * 1024, ge=1024, le=100 * 1024 * 1024)

    @field_validator(
        "smtp_host", "smtp_username", "smtp_password_file", "smtp_ca_file", mode="before"
    )
    @classmethod
    def _empty_is_unset(cls, value: object) -> object:
        # Compose passes unset optional variables as empty strings.
        return None if value == "" else value

    @model_validator(mode="after")
    def _check(self) -> Self:
        parts = urlsplit(self.public_url)
        if parts.scheme != "https" or not parts.hostname or parts.path not in ("", "/"):
            raise ValueError(
                "BACKEND_PUBLIC_URL must be an https origin, e.g. https://wiki.example.com"
            )
        if self.password_hash_profile == "test" and self.environment != "test":  # noqa: S105  # nosec B105
            raise ValueError(
                "BACKEND_PASSWORD_HASH_PROFILE=test is only allowed in the test environment"
            )
        return self

    @cached_property
    def public_origin(self) -> str:
        """``scheme://host[:port]`` of the public URL, compared with the ``Origin`` header."""
        return self.public_url.rstrip("/")

    @cached_property
    def public_hostname(self) -> str:
        """Host name of the public URL; the WebAuthn relying party id."""
        return urlsplit(self.public_url).hostname or ""

    @property
    def smtp_enabled(self) -> bool:
        return self.smtp_host is not None


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings; invalid environment fails here, at startup."""
    return Settings()
