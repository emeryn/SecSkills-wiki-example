"""Operator commands: ``python -m app.cli <command>``."""

import argparse
import sys
from collections.abc import Callable
from pathlib import Path

from alembic import command
from alembic.config import Config

from app.core.bootstrap import import_tls
from app.core.config import get_settings
from app.core.context import AppContext, build_context
from app.core.crypto import FieldCipher, decode_key
from app.core.db import DbRole, create_db_engine
from app.core.errors import AppError
from app.core.logging import configure_logging
from app.core.secrets import SecretsProvider, build_secrets_provider
from app.services import (
    audit_service,
    backup_service,
    bootstrap_admin,
    honeytoken_service,
    restore_test,
)
from app.services.audit_service import SYSTEM
from app.services.backup_archive import BackupFormatError
from app.services.backup_service import RestoreError

ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"


def migrate() -> int:
    """Apply migrations, then create the bootstrap administrator if none exists."""
    settings = get_settings()
    command.upgrade(Config(str(ALEMBIC_INI)), "head")
    secrets = build_secrets_provider(settings)
    engine = create_db_engine(settings, secrets, role="owner")
    ctx = build_context(settings, engine, secrets)
    with ctx.sessions() as db:
        bootstrap_admin.ensure_bootstrap_admin(
            db, ctx, secrets.read(bootstrap_admin.BOOTSTRAP_PASSWORD_SECRET)
        )
    engine.dispose()
    return 0


def admin_password() -> int:
    """Print the bootstrap administrator password while it has not been replaced."""
    settings = get_settings()
    secrets = build_secrets_provider(settings)
    engine = create_db_engine(settings, secrets, role="runtime")
    ctx = build_context(settings, engine, secrets)
    with ctx.sessions() as db:
        valid = bootstrap_admin.bootstrap_password_still_valid(db)
    engine.dispose()
    if not valid:
        print("The bootstrap password has already been replaced.", file=sys.stderr)
        return 1
    print(f"Username: {bootstrap_admin.BOOTSTRAP_USERNAME}")
    print(f"Password: {secrets.read(bootstrap_admin.BOOTSTRAP_PASSWORD_SECRET)}")
    print("You will be asked to choose a new password and enroll a second factor.")
    return 0


def audit_verify() -> int:
    """Recompute the audit hash chain; exit 1 at the first tampered row."""
    settings = get_settings()
    secrets = build_secrets_provider(settings)
    engine = create_db_engine(settings, secrets, role="runtime")
    ctx = build_context(settings, engine, secrets)
    with ctx.sessions() as db:
        broken = audit_service.verify_chain(db)
    engine.dispose()
    if broken is not None:
        print(f"Audit chain broken at event {broken}", file=sys.stderr)
        return 1
    print("Audit chain intact")
    return 0


def import_tls_command(cert: Path, key: Path) -> int:
    """Install a TLS certificate chain and key for the reverse proxy (run in the init container)."""
    import_tls(get_settings().secrets_dir, cert.read_bytes(), key.read_bytes())
    print("Certificate imported. Restart the frontend service to use it.")
    return 0


def _runtime_context(role: DbRole = "runtime") -> tuple[AppContext, SecretsProvider]:
    settings = get_settings()
    secrets = build_secrets_provider(settings)
    engine = create_db_engine(settings, secrets, role=role)
    return build_context(settings, engine, secrets), secrets


def backup() -> int:
    """Create an encrypted backup now (also applies the retention count)."""
    ctx, secrets = _runtime_context()
    key = decode_key(secrets.read(backup_service.BACKUP_KEY_SECRET))
    settings = ctx.settings
    with ctx.sessions() as db:
        info = backup_service.run_scheduled(
            db,
            ctx.engine,
            key,
            settings.backups_dir,
            settings.attachments_dir,
            settings.backup_retention_count,
        )
    ctx.engine.dispose()
    print(f"Backup created: {info.name} ({info.size_bytes} bytes)")
    return 0


def list_backups() -> int:
    """List the backups in the backups volume, newest first."""
    for info in backup_service.list_backups(get_settings().backups_dir):
        print(f"{info.name}\t{info.size_bytes}\t{info.created_at.isoformat()}")
    return 0


def _backup_path(name: str | None) -> Path:
    backups = backup_service.list_backups(get_settings().backups_dir)
    if name is None:
        if not backups:
            raise SystemExit("No backup found")
        return backups[0].path
    found = next((info.path for info in backups if info.name == name), None)
    if found is None:
        raise SystemExit(f"Backup not found: {name}")
    return found


def restore_backup(name: str | None, replace: bool) -> int:
    """Restore a backup into this installation's database (owner role); stop the backend first."""
    ctx, secrets = _runtime_context(role="owner")
    key = decode_key(secrets.read(backup_service.BACKUP_KEY_SECRET))
    try:
        report = backup_service.restore(
            ctx.engine, key, _backup_path(name), ctx.settings.attachments_dir, replace=replace
        )
    except (RestoreError, BackupFormatError) as exc:
        print(f"Restore failed: {exc}", file=sys.stderr)
        return 1
    finally:
        ctx.engine.dispose()
    print(f"Restored: {backup_service.describe(report)}")
    return 0


def restore_test_command(admin_url: str, name: str | None) -> int:
    """Restore a backup (default: the newest) into a scratch database and verify it."""
    settings = get_settings()
    secrets = build_secrets_provider(settings)
    key = decode_key(secrets.read(backup_service.BACKUP_KEY_SECRET))
    cipher = FieldCipher(decode_key(secrets.read("app/master.key")))
    path = _backup_path(name)
    try:
        report = restore_test.run(admin_url, key, path, cipher)
    except (RestoreError, BackupFormatError) as exc:
        print(f"Restore test FAILED for {path.name}: {exc}", file=sys.stderr)
        return 1
    print(f"Restore test passed for {path.name}: {backup_service.describe(report)}")
    return 0


def unblock_ip(ip: str) -> int:
    """Remove an IP from the honeytoken block list (when no administrator can sign in)."""
    ctx, _ = _runtime_context()
    with ctx.sessions() as db:
        try:
            honeytoken_service.unblock(db, ctx, ip, SYSTEM)
        except AppError:
            print(f"Not blocked: {ip}", file=sys.stderr)
            return 1
    ctx.engine.dispose()
    print(f"Unblocked: {ip}")
    return 0


def main(argv: list[str] | None = None) -> int:
    configure_logging(get_settings().log_level)
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("migrate", help=migrate.__doc__)
    sub.add_parser("admin-password", help=admin_password.__doc__)
    sub.add_parser("audit-verify", help=audit_verify.__doc__)
    tls = sub.add_parser("import-tls", help=import_tls_command.__doc__)
    tls.add_argument("--cert", type=Path, required=True)
    tls.add_argument("--key", type=Path, required=True)
    sub.add_parser("backup", help=backup.__doc__)
    sub.add_parser("list-backups", help=list_backups.__doc__)
    restore = sub.add_parser("restore-backup", help=restore_backup.__doc__)
    restore.add_argument("--name", help="Backup file name (default: newest)")
    restore.add_argument("--replace", action="store_true", help="Overwrite a non-empty database")
    check = sub.add_parser("restore-test", help=restore_test_command.__doc__)
    check.add_argument("--admin-url", required=True, help="Superuser URL of a scratch server")
    check.add_argument("--name", help="Backup file name (default: newest)")
    unblock = sub.add_parser("unblock-ip", help=unblock_ip.__doc__)
    unblock.add_argument("ip")
    args = parser.parse_args(argv)
    commands: dict[str, Callable[[], int]] = {
        "migrate": migrate,
        "admin-password": admin_password,
        "audit-verify": audit_verify,
        "import-tls": lambda: import_tls_command(args.cert, args.key),
        "backup": backup,
        "list-backups": list_backups,
        "restore-backup": lambda: restore_backup(args.name, args.replace),
        "restore-test": lambda: restore_test_command(args.admin_url, args.name),
        "unblock-ip": lambda: unblock_ip(args.ip),
    }
    return commands[args.command]()


if __name__ == "__main__":
    sys.exit(main())
