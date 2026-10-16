"""Encrypted backups of the database and attachments, restore and restore test.

Backups are logical (``COPY`` through the database driver, no ``pg_dump`` process) and taken in a
read-only repeatable-read transaction, so every table comes from the same snapshot. Sessions,
idempotency keys, sign-in throttling and reset tokens are not backed up: a restore must not
revive credentials. Personal data stays encrypted under the master key, which is not in backups:
keep ``app/master.key`` and ``app/backup.key`` safe, apart from the backups.
"""

import hashlib
import json
import logging
import os
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import psycopg
from sqlalchemy import Connection, Engine, Table, select, text
from sqlalchemy.orm import Session

from app.models import Attachment, Base
from app.services import audit_service
from app.services.audit_service import SYSTEM
from app.services.backup_archive import ArchiveReader, ArchiveWriter

logger = logging.getLogger(__name__)

FORMAT_VERSION = 1
BACKUP_KEY_SECRET = "app/backup.key"  # noqa: S105  # nosec B105
FILE_PATTERN = re.compile(r"^wiki-backup-\d{8}T\d{6}Z\.wbk$")
# Credentials must not be revived; embeddings are rebuilt by the worker after a restore.
EXCLUDED_TABLES = frozenset(
    {"sessions", "idempotency_keys", "auth_throttle", "password_reset_tokens", "page_chunks"}
)
_STORAGE_KEY = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
_READ_CHUNK = 256 * 1024


class RestoreError(RuntimeError):
    """The backup cannot be restored into this database; the message says why."""


@dataclass(frozen=True)
class BackupInfo:
    name: str
    path: Path
    size_bytes: int
    created_at: datetime


@dataclass
class RestoreReport:
    rows: dict[str, int] = field(default_factory=dict)
    attachments: int = 0
    missing_attachments: list[str] = field(default_factory=list)


def backed_up_tables() -> list[Table]:
    """Tables in dependency order (circular foreign keys are deferrable)."""
    return [t for t in Base.metadata.sorted_tables if t.name not in EXCLUDED_TABLES]


def _quote(conn: Connection, name: str) -> str:
    return conn.dialect.identifier_preparer.quote(name)


def _copy_sql(conn: Connection, table: str, columns: list[str], direction: str) -> str:
    # Identifiers come from the ORM metadata and are quoted; nothing user-supplied is in them.
    cols = ", ".join(_quote(conn, c) for c in columns)
    return f"COPY {_quote(conn, table)} ({cols}) {direction} (FORMAT csv)"


def _driver(conn: Connection) -> psycopg.Connection[Any]:
    """The psycopg connection under ``conn``, sharing its transaction (needed for COPY)."""
    return cast(psycopg.Connection[Any], conn.connection.dbapi_connection)


def _count(conn: Connection, table: str) -> int:
    return int(conn.scalar(text(f"SELECT count(*) FROM {_quote(conn, table)}")) or 0)  # noqa: S608  # nosec B608


def _file_chunks(path: Path) -> Iterator[bytes]:
    with path.open("rb") as handle:
        while chunk := handle.read(_READ_CHUNK):
            yield chunk


def _dump_tables(conn: Connection, writer: ArchiveWriter) -> tuple[dict[str, int], dict[str, str]]:
    rows: dict[str, int] = {}
    for table in backed_up_tables():
        columns = [c.name for c in table.columns]
        # Same snapshot as the COPY: the count is what a restore must find.
        rows[table.name] = _count(conn, table.name)
        sql = _copy_sql(conn, table.name, columns, "TO STDOUT")
        with _driver(conn).cursor() as cursor, cursor.copy(sql) as copy:
            writer.add(f"db/{table.name}.csv", (bytes(data) for data in copy))
    files = {
        key: sha for key, sha in conn.execute(select(Attachment.storage_key, Attachment.sha256))
    }
    return rows, files


def create_backup(
    engine: Engine, key: bytes, backups_dir: Path, attachments_dir: Path
) -> BackupInfo:
    """Write a new backup file (mode 0400); a partial file never has the final name."""
    created = datetime.now(UTC).replace(microsecond=0)
    name = f"wiki-backup-{created:%Y%m%dT%H%M%SZ}.wbk"
    final = backups_dir / name
    partial = backups_dir / f".{name}.partial"
    fd = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as out:
            writer = ArchiveWriter(out, key)
            with engine.connect() as base:
                conn = base.execution_options(isolation_level="REPEATABLE READ")
                with conn.begin():
                    conn.execute(text("SET TRANSACTION READ ONLY"))
                    conn.execute(text("SET LOCAL statement_timeout = 0"))
                    revision = conn.scalar(text("SELECT version_num FROM alembic_version"))
                    tables = {t.name: [c.name for c in t.columns] for t in backed_up_tables()}
                    writer.add_json(
                        "header.json",
                        {
                            "format": FORMAT_VERSION,
                            "created_at": created.isoformat(),
                            "revision": revision,
                            "tables": tables,
                        },
                    )
                    rows, files = _dump_tables(conn, writer)
            missing = []
            for storage_key in sorted(files):
                path = attachments_dir / storage_key
                if not _STORAGE_KEY.match(storage_key) or not path.is_file():
                    missing.append(storage_key)
                    continue
                writer.add(f"attachments/{storage_key}", _file_chunks(path))
            stored = {k: v for k, v in files.items() if k not in missing}
            writer.add_json(
                "summary.json", {"rows": rows, "attachments": stored, "missing": missing}
            )
            writer.close()
            out.flush()
            os.fsync(out.fileno())
        os.chmod(partial, 0o400)
        os.replace(partial, final)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    return BackupInfo(name, final, final.stat().st_size, created)


def list_backups(backups_dir: Path) -> list[BackupInfo]:
    """Complete backups, newest first."""
    found = []
    for path in backups_dir.iterdir() if backups_dir.is_dir() else []:
        if FILE_PATTERN.match(path.name) and path.is_file():
            stamp = datetime.strptime(path.name[12:28], "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
            found.append(BackupInfo(path.name, path, path.stat().st_size, stamp))
    return sorted(found, key=lambda info: info.name, reverse=True)


def prune(backups_dir: Path, keep: int) -> list[str]:
    removed = []
    for info in list_backups(backups_dir)[keep:]:
        info.path.chmod(0o600)
        info.path.unlink()
        removed.append(info.name)
    return removed


def run_scheduled(
    db: Session, engine: Engine, key: bytes, backups_dir: Path, attachments_dir: Path, keep: int
) -> BackupInfo:
    """Backup, retention, and an audit event the dashboard reads."""
    info = create_backup(engine, key, backups_dir, attachments_dir)
    removed = prune(backups_dir, keep)
    audit_service.record(
        db,
        SYSTEM,
        "backup.created",
        target_type="backup",
        target_id=info.name,
        after={"size_bytes": info.size_bytes, "pruned": removed},
    )
    db.commit()
    logger.info("Backup created", extra={"backup": info.name, "size_bytes": info.size_bytes})
    return info


def _restore_table(conn: Connection, name: str, columns: list[str], data: Iterator[bytes]) -> None:
    table = Base.metadata.tables.get(name)
    if table is None or name in EXCLUDED_TABLES:
        raise RestoreError(f"Unknown table in backup: {name}")
    if set(columns) != {c.name for c in table.columns}:
        raise RestoreError(f"Columns of {name} differ from this version")
    sql = _copy_sql(conn, name, columns, "FROM STDIN")
    with _driver(conn).cursor() as cursor, cursor.copy(sql) as copy:
        for chunk in data:
            copy.write(chunk)


def _restore_file(directory: Path, storage_key: str, data: Iterator[bytes]) -> tuple[Path, str]:
    if not _STORAGE_KEY.match(storage_key):
        raise RestoreError("Invalid attachment name in backup")
    target = (directory / storage_key).resolve()
    if not target.is_relative_to(directory.resolve()):
        raise RestoreError("Invalid attachment name in backup")
    digest = hashlib.sha256()
    partial = target.with_name(f".{storage_key}.restore")
    with partial.open("wb") as handle:
        for chunk in data:
            digest.update(chunk)
            handle.write(chunk)
    partial.replace(target)
    return target, digest.hexdigest()


def _prepare(conn: Connection, header: dict[str, Any], replace: bool) -> None:
    if header.get("format") != FORMAT_VERSION:
        raise RestoreError("Unsupported backup format")
    revision = conn.scalar(text("SELECT version_num FROM alembic_version"))
    if revision != header.get("revision"):
        raise RestoreError(
            f"The backup is at schema revision {header.get('revision')}, the database at "
            f"{revision}: restore with the application version that made the backup"
        )
    users = conn.scalar(text("SELECT count(*) FROM users"))
    if users and not replace:
        raise RestoreError("The database is not empty; pass --replace to overwrite it")
    if replace:
        names = ", ".join(_quote(conn, t.name) for t in Base.metadata.sorted_tables)
        conn.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))  # nosec B608
    conn.execute(text("SET CONSTRAINTS ALL DEFERRED"))
    conn.execute(text("SET LOCAL statement_timeout = 0"))


def _verify(
    conn: Connection, summary: dict[str, Any], report: RestoreReport, hashes: dict[str, str]
) -> None:
    for name, expected in summary["rows"].items():
        actual = _count(conn, name)
        if actual != expected:
            raise RestoreError(f"{name}: {actual} rows restored, {expected} expected")
        report.rows[name] = actual
    for storage_key, sha in summary["attachments"].items():
        if hashes.get(storage_key) != sha:
            raise RestoreError(f"Attachment {storage_key} does not match its checksum")
    report.attachments = len(hashes)
    report.missing_attachments = list(summary.get("missing", []))


def _reset_sequences(conn: Connection) -> None:
    for table in Base.metadata.sorted_tables:
        for column in table.primary_key.columns:
            if column.autoincrement is True:
                quoted, col = _quote(conn, table.name), _quote(conn, column.name)
                conn.execute(
                    text(
                        f"SELECT setval(pg_get_serial_sequence(:t, :c), "  # noqa: S608  # nosec B608
                        f"coalesce((SELECT max({col}) FROM {quoted}), 1), "
                        f"(SELECT max({col}) FROM {quoted}) IS NOT NULL)"
                    ),
                    {"t": table.name, "c": column.name},
                )


def restore(
    engine: Engine, key: bytes, path: Path, attachments_dir: Path, *, replace: bool = False
) -> RestoreReport:
    """Restore into a migrated database (owner role), in one transaction; files are verified."""
    report = RestoreReport()
    written: list[Path] = []
    hashes: dict[str, str] = {}
    with path.open("rb") as stream:
        entries = ArchiveReader(stream, key).entries()
        name, data = next(entries)
        if name != "header.json":
            raise RestoreError("The backup has no header")
        header = cast(dict[str, Any], ArchiveReader.read_json(data))
        try:
            with engine.connect() as conn, conn.begin():
                _prepare(conn, header, replace)
                summary: dict[str, Any] | None = None
                for name, data in entries:
                    if name.startswith("db/") and name.endswith(".csv"):
                        table = name[3:-4]
                        _restore_table(conn, table, header["tables"].get(table, []), data)
                    elif name.startswith("attachments/"):
                        target, digest = _restore_file(attachments_dir, name[12:], data)
                        written.append(target)
                        hashes[name[12:]] = digest
                    elif name == "summary.json":
                        summary = cast(dict[str, Any], ArchiveReader.read_json(data))
                if summary is None:
                    raise RestoreError("The backup has no summary")
                _verify(conn, summary, report, hashes)
                _reset_sequences(conn)
                with Session(bind=conn) as session:
                    audit_service.record(
                        session,
                        SYSTEM,
                        "backup.restored",
                        target_type="backup",
                        target_id=path.name,
                        after={
                            "rows": sum(report.rows.values()),
                            "attachments": report.attachments,
                        },
                    )
        except BaseException:
            for file in written:
                file.unlink(missing_ok=True)
            raise
    return report


def describe(report: RestoreReport) -> str:
    return json.dumps(
        {
            "rows": report.rows,
            "attachments": report.attachments,
            "missing_attachments": report.missing_attachments,
        },
        sort_keys=True,
    )
