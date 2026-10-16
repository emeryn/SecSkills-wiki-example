# MCP endpoints

**Settings > MCP** controls two endpoints for AI clients (Model Context Protocol, Streamable
HTTP), both authenticated by personal API keys:

- `/mcp` (on by default): `search_pages`, `read_page`, `create_page`, `update_page`, with the
  key owner's rights narrowed by the key's scopes. Same checks as the web interface: restricted
  spaces stay invisible, writes need the editor role, edits are refused if the page changed.
- `/mcp/admin` (**off by default**): `list_users`, `list_audit_events`, `list_blocked_ips`,
  `unblock_ip`, `revoke_user_sessions`. Needs a key with the `admin` scope belonging to an active
  administrator. Destructive tools refuse to run without `confirm: true`. No tool reads page
  content.

Keys: at least 32 random bytes, stored hashed, shown once, expiring after at most a year (30
days with the `admin` scope), revocable by their owner; they stop working when the account is
disabled. Creating a key asks the user to confirm their identity.

Every tool call is audited (`mcp.tool_call`): key, tool, arguments with page content masked,
outcome and duration. **Requests per minute per key** limits each key; Nginx adds a per-IP limit.
Browsers cannot call these endpoints from another site: a foreign `Origin` is refused.
