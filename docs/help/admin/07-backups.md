# Backups and restore

The `worker` service backs up the database and the attachments every 24 hours
(`BACKEND_BACKUP_INTERVAL_HOURS`) into the `backups` volume, and keeps the last 14
(`BACKEND_BACKUP_RETENTION_COUNT`). Backups are encrypted with AES-256-GCM and checked on restore:
a modified or truncated file is refused.

- `make backup` takes a backup now.
- `make restore-test` restores the newest backup into a throwaway database and checks the row
  counts, the attachment checksums, the audit chain and the master key. Run it regularly and after
  every upgrade.

## Keep the keys apart from the backups

Copy `app/backup.key` **and** `app/master.key` from the `secrets` volume to a safe place, apart
from the backup copies. Without the backup key a backup cannot be read; without the master key,
the names and email addresses it contains cannot be decrypted.

Sessions, reset links and sign-in throttling are not backed up: users sign in again after a
restore.

## Restore

1. Run the same application version, with the same `secrets` volume (or the saved keys).
2. `docker compose stop backend worker`
3. `docker compose run --rm worker python -m app.cli restore-backup --replace`
   restores the newest backup; add `--name wiki-backup-<date>.wbk` for another one.
4. `docker compose start backend worker`
