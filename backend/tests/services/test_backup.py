"""Encrypted backups: round trip, tampering, truncation, wrong key, restore test."""

import hashlib
import io
import os
import secrets
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select

from app.core.context import AppContext
from app.models import Attachment, AuditEvent, AuthSession, Space, User
from app.services import audit_service, backup_service, restore_test
from app.services.backup_archive import ArchiveReader, ArchiveWriter, BackupFormatError
from app.services.backup_service import RestoreError
from tests.conftest import ADMIN_URL
from tests.helpers import make_space, make_user, sign_in

KEY = secrets.token_bytes(32)
CONTENT = b"%PDF-1.7 attachment bytes " * 100


@pytest.fixture
def backups(tmp_path: Path) -> Path:
    directory = tmp_path / "backups"
    directory.mkdir()
    return directory


def _attachment(ctx: AppContext, space_key: str) -> Path:
    storage_key = secrets.token_hex(16)
    path = ctx.settings.attachments_dir / storage_key
    path.write_bytes(CONTENT)
    with ctx.sessions() as db:
        page_id = db.scalar(select(Space.home_page_id).where(Space.key == space_key))
        db.add(
            Attachment(
                page_id=page_id,
                filename="manual.pdf",
                storage_key=storage_key,
                content_type="application/pdf",
                size_bytes=len(CONTENT),
                sha256=hashlib.sha256(CONTENT).hexdigest(),
                inline_allowed=False,
            )
        )
        db.commit()
    return path


@pytest.fixture
def populated(client: TestClient, ctx: AppContext) -> Path:
    owner = make_user(ctx, "owner", email="owner@example.com")
    space = make_space(ctx, "Handbook", owner)
    sign_in(client, owner)
    return _attachment(ctx, space)


def _counts(ctx: AppContext) -> dict[str, int]:
    with ctx.sessions() as db:
        return {
            model.__tablename__: db.scalar(select(func.count()).select_from(model)) or 0
            for model in (User, Space, Attachment, AuditEvent)
        }


def test_round_trip_restores_rows_and_files(
    ctx: AppContext, engine: Engine, owner_engine: Engine, backups: Path, populated: Path
) -> None:
    before = _counts(ctx)
    info = backup_service.create_backup(engine, KEY, backups, ctx.settings.attachments_dir)
    assert backup_service.list_backups(backups)[0].name == info.name
    assert os.stat(info.path).st_mode & 0o777 == 0o400
    raw = info.path.read_bytes()
    assert b"owner" not in raw and b"Handbook" not in raw and CONTENT[:20] not in raw

    populated.unlink()
    report = backup_service.restore(
        owner_engine, KEY, info.path, ctx.settings.attachments_dir, replace=True
    )
    assert populated.read_bytes() == CONTENT
    assert report.attachments == 1
    after = _counts(ctx)
    # The restore itself is audited.
    assert after == {**before, "audit_events": before["audit_events"] + 1}
    with ctx.sessions() as db:
        assert audit_service.verify_chain(db) is None
        assert db.scalar(select(func.count()).select_from(AuthSession)) == 0
        # The sequence continues after the restored rows.
        audit_service.record(db, audit_service.SYSTEM, "test.after_restore")
        db.commit()


def test_restore_refuses_a_non_empty_database(
    ctx: AppContext, engine: Engine, owner_engine: Engine, backups: Path, populated: Path
) -> None:
    info = backup_service.create_backup(engine, KEY, backups, ctx.settings.attachments_dir)
    with pytest.raises(RestoreError, match="not empty"):
        backup_service.restore(owner_engine, KEY, info.path, ctx.settings.attachments_dir)


@pytest.mark.parametrize("damage", ["flip", "truncate", "append"])
def test_damaged_backup_is_refused_and_nothing_changes(
    ctx: AppContext,
    engine: Engine,
    owner_engine: Engine,
    backups: Path,
    populated: Path,
    damage: str,
) -> None:
    info = backup_service.create_backup(engine, KEY, backups, ctx.settings.attachments_dir)
    data = bytearray(info.path.read_bytes())
    if damage == "flip":
        data[len(data) // 2] ^= 0x01
    elif damage == "truncate":
        data = data[: len(data) - 20]
    else:
        data += b"extra"
    damaged = backups / "damaged.wbk"
    damaged.write_bytes(bytes(data))
    before = _counts(ctx)
    with pytest.raises(BackupFormatError):
        backup_service.restore(
            owner_engine, KEY, damaged, ctx.settings.attachments_dir, replace=True
        )
    assert _counts(ctx) == before


def test_wrong_key_is_reported(
    ctx: AppContext, engine: Engine, owner_engine: Engine, backups: Path, populated: Path
) -> None:
    info = backup_service.create_backup(engine, KEY, backups, ctx.settings.attachments_dir)
    with pytest.raises(BackupFormatError, match="another backup key"):
        backup_service.restore(
            owner_engine, secrets.token_bytes(32), info.path, ctx.settings.attachments_dir
        )


def test_archive_frames_large_entries() -> None:
    out = io.BytesIO()
    writer = ArchiveWriter(out, KEY)
    payload = secrets.token_bytes(3 * 1024 * 1024)
    writer.add("big", [payload])
    writer.add_json("small", {"a": 1})
    writer.close()
    out.seek(0)
    entries = {name: b"".join(data) for name, data in ArchiveReader(out, KEY).entries()}
    assert entries == {"big": payload, "small": b'{"a": 1}'}


def test_retention_keeps_the_newest(backups: Path) -> None:
    for stamp in ("20261001T020000Z", "20261002T020000Z", "20261003T020000Z"):
        (backups / f"wiki-backup-{stamp}.wbk").write_bytes(b"x")
    removed = backup_service.prune(backups, keep=2)
    assert removed == ["wiki-backup-20261001T020000Z.wbk"]
    assert [b.name for b in backup_service.list_backups(backups)] == [
        "wiki-backup-20261003T020000Z.wbk",
        "wiki-backup-20261002T020000Z.wbk",
    ]


def test_restore_test_round_trip(
    ctx: AppContext, engine: Engine, backups: Path, populated: Path
) -> None:
    assert ADMIN_URL is not None
    info = backup_service.create_backup(engine, KEY, backups, ctx.settings.attachments_dir)
    report = restore_test.run(ADMIN_URL, KEY, info.path, ctx.cipher)
    assert report.rows["users"] == 1
    assert report.attachments == 1
    assert report.missing_attachments == []
