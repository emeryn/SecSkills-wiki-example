# Honeytokens and blocked IPs

Honeytokens are traps no legitimate user touches:

- **Decoy usernames** (by default `administrator` and `sysadmin`): a sign-in attempt with one of
  them answers like a wrong password, then blocks the client IP.
- **Trap URLs** such as `/.env`, `/.git/` or `/wp-login.php`, requested only by scanners.

Each hit records a *critical* audit event, sent to syslog and the notifications. The IP is blocked
for **Block duration** minutes (0: until unblocked). Unblock it in **Settings > Security**, or with
`docker compose exec backend python -m app.cli unblock-ip <ip>` when no administrator can sign in.

The client IP is read from `X-Forwarded-For` behind `BACKEND_TRUSTED_PROXY_COUNT` proxies (1: the
bundled Nginx). When that count does not match the forwarded header, hits are recorded but no IP
is blocked, so a proxy is never blocked by mistake. Increase the count when you add a reverse
proxy in front.
