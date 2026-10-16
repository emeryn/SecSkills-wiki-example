"""Restore round trip into a scratch database: proves a backup is usable, not only present.

Run by ``make restore-test`` against a throwaway PostgreSQL. The backup is restored into a freshly
migrated database, then the row counts, the attachment checksums, the audit hash chain and the
master key (decrypting personal data) are checked. The scratch database is dropped afterwards.
"""

import shutil
import tempfile
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.core.crypto import FieldCipher
from app.models import User
from app.services import audit_service, backup_service
from app.services.backup_service import RestoreError, RestoreReport

SCRATCH_DATABASE = "wiki_restore_test"
ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


def _create_scratch(admin_url: str) -> str:
    """Empty database owned by ``app_owner`` (roles created if missing); returns its owner URL."""
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f"DROP DATABASE IF EXISTS {SCRATCH_DATABASE} WITH (FORCE)"))
        for role in ("app_owner", "app_runtime"):
            if not conn.scalar(text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role}):
                conn.execute(text(f"CREATE ROLE {role} LOGIN"))
        conn.execute(text(f"CREATE DATABASE {SCRATCH_DATABASE} OWNER app_owner"))
    admin.dispose()
    url = make_url(admin_url).set(database=SCRATCH_DATABASE, username="app_owner", password=None)
    return url.render_as_string(hide_password=False)


def _drop_scratch(admin_url: str) -> None:
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f"DROP DATABASE IF EXISTS {SCRATCH_DATABASE} WITH (FORCE)"))
    admin.dispose()


def run(admin_url: str, backup_key: bytes, backup: Path, cipher: FieldCipher) -> RestoreReport:
    owner_url = _create_scratch(admin_url)
    attachments = Path(tempfile.mkdtemp(prefix="restore-test-"))
    engine = create_engine(owner_url)
    try:
        config = Config(str(ALEMBIC_INI))
        with engine.begin() as conn:
            config.attributes["connection"] = conn
            command.upgrade(config, "head")
        report = backup_service.restore(engine, backup_key, backup, attachments)
        with Session(engine) as db:
            broken = audit_service.verify_chain(db)
            if broken is not None:
                raise RestoreError(f"Audit chain broken at event {broken} after restore")
            wrapped = db.scalar(select(User.dek_wrapped).limit(1))
        if wrapped is not None:
            try:
                cipher.unwrap(wrapped)
            except Exception as exc:
                raise RestoreError(
                    "Personal data cannot be decrypted: the master key differs from the backup's"
                ) from exc
        return report
    finally:
        engine.dispose()
        shutil.rmtree(attachments, ignore_errors=True)
        _drop_scratch(admin_url)
