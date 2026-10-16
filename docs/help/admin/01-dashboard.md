# Administration overview

**Admin > Overview** summarizes the selected period (24 hours, 7 days or 30 days). Every number
opens the matching list.

- **Failed sign-ins** and **Honeytoken alerts** open the audit log, filtered.
- **Server errors** lists 5xx responses and failed scheduled jobs with their request ID. Look the
  request ID up in the application logs for details: stack traces are never shown in the UI.
- **Backups** shows *Overdue* when the last backup is more than 26 hours old. See
  [Backups and restore](/help/admin/backups).

Administrators have no implicit access to the content of restricted spaces.
