# Settings

Each section is saved on its own; **Reset to default** deletes its saved values. Changing syslog,
email, webhook or security settings asks you to confirm your identity.

Outbound connections need the egress overlay:
`docker compose -f docker-compose.yml -f deploy/compose.egress.yml up -d`.

## Destinations are checked

Hosts and URLs are checked when saved and again at each connection. Loopback, link-local (cloud
metadata) and reserved addresses are always refused; private addresses only pass when their
network is listed in **Security > Allowed private networks**. The connection goes to the checked
address, TLS certificates are always verified (add an internal CA as PEM) and redirects are not
followed.

## Sections

- **Remote syslog**: RFC 5424 over TLS, port 6514 by default. Audit events and the logs from the
  chosen level. While the server is unreachable, up to 10,000 messages wait in memory; the oldest
  are dropped first and their number is reported.
- **Email (SMTPS)**: implicit TLS only. When `BACKEND_SMTP_*` variables are set, this section is
  read-only (*Managed by environment*).
- **Webhook**: JSON POST. Receivers check `X-Signature: sha256=<hex>`, the HMAC-SHA256 of
  `<X-Signature-Timestamp>.<body>` with the secret, and refuse old timestamps.
- **Notifications**: server errors and security alerts, by email and to the webhook. The same
  alert is sent at most every 15 minutes per channel, and a channel sends at most 20 messages an
  hour.
- **Privacy**: masks email and IP addresses in logs, syslog messages and notifications.
- **Security**: see [Honeytokens and blocked IPs](/help/admin/honeytokens).

**Send test** uses the saved values, three times a minute at most. Secrets (SMTP password, webhook
secret) are never shown again once saved: leave the field empty to keep them.
