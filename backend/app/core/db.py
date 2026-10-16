"""Database engines. The API uses the DML-only runtime role; migrations use the owner role."""

from typing import Literal

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import URL

from app.core.config import Settings
from app.core.secrets import SecretsProvider

DbRole = Literal["runtime", "owner"]

# Created by deploy/postgres/initdb; migrations and pg_hba.conf reference these names.
DATABASE_NAME = "app"
ROLE_NAMES: dict[DbRole, str] = {"runtime": "app_runtime", "owner": "app_owner"}


def create_db_engine(settings: Settings, secrets: SecretsProvider, role: DbRole) -> Engine:
    """Create an engine over TLS with full certificate and host name verification."""
    url = URL.create(
        "postgresql+psycopg",
        username=ROLE_NAMES[role],
        password=secrets.read(f"db/{role}_password"),
        host=settings.db_host,
        port=settings.db_port,
        database=DATABASE_NAME,
    )
    return create_engine(
        url,
        pool_size=settings.db_pool_size,
        pool_pre_ping=True,
        connect_args={
            "sslmode": "verify-full",
            "sslrootcert": str(secrets.file_path("db/ca.crt")),
            "connect_timeout": settings.db_connect_timeout_seconds,
            "application_name": f"wiki-{role}",
        },
    )


def database_is_available(engine: Engine) -> bool:
    """Return True when a trivial query succeeds."""
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception:
        return False
    return True
