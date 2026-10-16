import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url

from app.core.bootstrap import bootstrap
from app.core.config import Settings
from app.core.context import AppContext
from app.core.secrets import FileSecretsProvider
from app.main import create_app
from app.models import Base

ADMIN_URL = os.environ.get("TEST_DATABASE_ADMIN_URL")
TEST_DB = "wiki_test"
requires_db = pytest.mark.skipif(ADMIN_URL is None, reason="TEST_DATABASE_ADMIN_URL not set")


@pytest.fixture(scope="session")
def secrets_provider(tmp_path_factory: pytest.TempPathFactory) -> FileSecretsProvider:
    base = tmp_path_factory.mktemp("secrets")
    gid = os.getegid()
    bootstrap(base, ["testserver"], db_gid=gid, web_gid=gid)
    return FileSecretsProvider(base)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    attachments = tmp_path / "attachments"
    attachments.mkdir()
    return Settings(
        environment="test",
        sandbox_enabled=False,
        max_request_body_bytes=8192,
        password_hash_profile="test",
        public_url="https://testserver",
        attachments_dir=attachments,
    )


@pytest.fixture(scope="session")
def database() -> Iterator[str]:
    """Fresh database migrated as the owner role; yields the runtime role URL."""
    if ADMIN_URL is None:
        pytest.skip("TEST_DATABASE_ADMIN_URL not set")
    admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)"))
        for role in ("app_owner", "app_runtime"):
            exists = conn.scalar(text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role})
            if not exists:
                conn.execute(text(f"CREATE ROLE {role} LOGIN"))
        conn.execute(text(f"CREATE DATABASE {TEST_DB} OWNER app_owner"))
    admin.dispose()

    base_url = make_url(ADMIN_URL).set(database=TEST_DB)
    superuser = create_engine(base_url, isolation_level="AUTOCOMMIT")
    with superuser.connect() as conn:
        conn.execute(text("REVOKE ALL ON SCHEMA public FROM PUBLIC"))
        conn.execute(text("GRANT USAGE ON SCHEMA public TO app_runtime"))
        conn.execute(
            text(
                "ALTER DEFAULT PRIVILEGES FOR ROLE app_owner IN SCHEMA public "
                "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_runtime"
            )
        )
        conn.execute(
            text(
                "ALTER DEFAULT PRIVILEGES FOR ROLE app_owner IN SCHEMA public "
                "GRANT USAGE, SELECT ON SEQUENCES TO app_runtime"
            )
        )
    superuser.dispose()

    owner = create_engine(base_url.set(username="app_owner", password=None))
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    with owner.begin() as conn:
        config.attributes["connection"] = conn
        command.upgrade(config, "head")
    owner.dispose()
    yield base_url.set(username="app_runtime", password=None).render_as_string(hide_password=False)


@pytest.fixture
def engine(database: str) -> Iterator[Engine]:
    engine = create_engine(database)
    yield engine
    engine.dispose()
    assert ADMIN_URL is not None
    cleaner = create_engine(make_url(ADMIN_URL).set(database=TEST_DB), isolation_level="AUTOCOMMIT")
    tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
    with cleaner.connect() as conn:
        conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    cleaner.dispose()


@pytest.fixture
def app(settings: Settings, engine: Engine, secrets_provider: FileSecretsProvider) -> FastAPI:
    return create_app(settings, engine=engine, secrets=secrets_provider)


@pytest.fixture
def ctx(app: FastAPI) -> AppContext:
    context: AppContext = app.state.context
    return context


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(
        app,
        base_url="https://testserver",
        headers={"X-Requested-With": "XMLHttpRequest"},
        raise_server_exceptions=False,
    ) as test_client:
        yield test_client


@pytest.fixture
def superuser_engine(database: str) -> Iterator[Engine]:
    assert ADMIN_URL is not None
    engine = create_engine(make_url(ADMIN_URL).set(database=TEST_DB))
    yield engine
    engine.dispose()


@pytest.fixture
def owner_engine(database: str) -> Iterator[Engine]:
    """Migration owner role: restores run with it."""
    engine = create_engine(make_url(database).set(username="app_owner"))
    yield engine
    engine.dispose()
