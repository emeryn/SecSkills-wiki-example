"""Alembic environment: migrations run as the database owner role, over TLS.

Tests and ``alembic revision --autogenerate`` against a throwaway database pass a connection in
``config.attributes["connection"]`` or a URL with ``-x url=...`` instead.
"""

from alembic import context
from sqlalchemy import Connection, create_engine

from app.core.config import get_settings
from app.core.db import create_db_engine
from app.core.logging import configure_logging
from app.core.secrets import build_secrets_provider
from app.models import Base

target_metadata = Base.metadata


def _run(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_offline() -> None:
    """Emit SQL to stdout without a connection (``alembic upgrade head --sql``)."""
    context.configure(
        url="postgresql+psycopg://",
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Apply migrations in a single transaction."""
    connection = context.config.attributes.get("connection")
    if connection is not None:
        _run(connection)
        return
    url = context.get_x_argument(as_dictionary=True).get("url")
    if url:
        engine = create_engine(url)
    else:
        settings = get_settings()
        configure_logging(settings.log_level)
        engine = create_db_engine(settings, build_secrets_provider(settings), role="owner")
    with engine.connect() as conn:
        _run(conn)
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
