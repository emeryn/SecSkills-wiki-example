# Audit log

Every security-relevant action is recorded: sign-ins and failures, two-factor changes, role and
membership changes, page deletion and restore, exports, settings changes, honeytoken hits and
backups.

- Filters (action, outcome, severity, dates, actor, IP) are part of the URL: share the link to
  share the view. Use `system` as actor for scheduled jobs.
- Click a row for the before and after values and the request ID.
- **Export CSV** downloads the filtered events (50,000 at most). It asks you to confirm your
  identity and is itself recorded. Cells a spreadsheet could run as a formula start with `'`.

The log is tamper-evident: each event is chained to the previous one by a hash. Check the chain
with `docker compose exec backend python -m app.cli audit-verify`.
