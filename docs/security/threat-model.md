# Threat Model: Wiki

Scope: v1 (local auth and single sign-on, spaces, pages, revisions, search, attachments, export, administration and operations, Ask the wiki, MCP endpoints). Update this file when SSO, RAG/LLM or MCP is enabled: each adds a trust boundary.

## Assets
| Asset | Why it matters |
|---|---|
| Page bodies, titles, revisions of restricted spaces | Confidential internal knowledge; titles alone can leak information |
| Attachments | Same confidentiality as pages; also a malware/polyglot vector |
| Credentials, sessions, MFA secrets, reset tokens | Account takeover |
| OIDC client secret, LDAP service account password | Impersonate the wiki at the IdP; read the directory |
| Page chunks and embeddings | Same confidentiality as the pages they come from |
| API keys | Act as their owner (and, with the admin scope, as an administrator) without MFA |
| Space memberships and global admin role | Control over who reads what |
| Audit trail | Evidence; must be tamper-evident |
| Master key, DB credentials (init-generated secrets volume) | Decrypt PII, full DB access |
| Backups | Contain everything above (personal data still encrypted under the master key) |
| Backup key (`app/backup.key`), outbound secrets (SMTP password, webhook secret) | Read backups; send mail or alerts as the wiki |

## Actors
Anonymous network user · authenticated user with no membership · Viewer / Editor / Space admin (possibly malicious insider) · Admin (no implicit read of restricted spaces) · operator with host access · compromised dependency or image.

## Trust boundaries
1. Browser → Nginx (TLS 1.3, hybrid `X25519MLKEM768`, rate limits, headers).
2. Nginx → backend (internal network; client IP from trusted proxy count only).
3. Backend → PostgreSQL (internal-only network, TLS, runtime DML role).
4. Backend → attachment storage volume (outside web root, random names, served only through the API after a permission check).
5. Rendered Markdown → browser DOM (stored content crosses back into the browser).
6. Backend and worker → outbound services: SMTP, syslog, webhooks. Destinations are set by administrators: SSRF-validated, address pinned, TLS verified, egress network opt-in.
7. Worker → backups volume (encrypted archives; the key stays in the secrets volume).
8. Identity provider and directory → backend: OIDC authorization responses arrive through the user's browser (attacker-controllable), tokens and keys over pinned TLS; LDAP answers over LDAPS/StartTLS. Their claims and groups decide who signs in and which space roles they get.
9. Backend and worker → inference server (LLM): prompts carry page excerpts the asker may read; the model's output comes back into the browser. Page content written by any editor reaches the model (prompt injection).
10. MCP clients → `/mcp`, `/mcp/admin`: programs holding an API key, outside the browser's protections (no cookies, no CSRF token); tool arguments are attacker-controllable, and the client may itself be steered by prompt injection.
11. Build pipeline → images (lockfiles, scans, cosign signatures).

## Top risks (STRIDE) and controls
| # | STRIDE | Threat | Control |
|---|---|---|---|
| 1 | Tampering / EoP | **Stored XSS** via Markdown, link schemes, image URLs, search snippets, file names | `markdown-it` `html: false`; DOMPurify; `javascript:`/`data:` dropped; remote images blocked; strict CSP + Trusted Types; snippets escaped then highlighted with fixed markers; SVG/HTML uploads refused |
| 2 | Info disclosure | **Title/existence leak** of unreadable pages via search, recent changes, favorites, link resolution, export, `404` vs `403` | Permission filter joined in SQL in the repository layer; one `readable_spaces` predicate reused everywhere; unauthorized object → `404`; parametrized IDOR tests over every route |
| 3 | EoP | **BOLA/IDOR**: page/attachment/revision IDs from another space | Every lookup scoped by `(space_id, id)` + membership check; attachment → page → space chain checked |
| 4 | EoP | Admin reads restricted space content | Admin permissions exclude content read; self-adding membership is audited and raises an alert |
| 5 | Spoofing | Credential stuffing, brute force, session theft | Argon2id, breached-password list, per-account + per-IP progressive delays, `__Host-session` cookie, rotation at login, MFA mandatory for admins, honeytoken decoy account |
| 6 | Tampering | CSRF, replayed or duplicate writes, lost updates | Custom header + CSRF token + `Origin`/`Sec-Fetch-Site`; `Idempotency-Key`; `If-Match` → `412` |
| 7 | Tampering / EoP | Malicious upload (polyglot, macro document, zip bomb, path in name) | Size limit at proxy and app; extension + magic bytes; image re-encoding; random stored names; `Content-Disposition: attachment` + `nosniff`; optional ClamAV |
| 8 | Tampering | Zip-slip / path traversal in export and storage | Server-generated slugs; sanitized entry names; paths resolved against a base directory |
| 9 | DoS | Huge pages, deep trees, expensive search/diff/export | 1 MB body, depth 5, page size ≤ 100, `statement_timeout`, rate limits on search/export/upload, bounded diff input |
| 10 | Repudiation | Silent membership or content destruction | Hash-chained append-only audit (membership, delete/restore, revision restore, export, permissions), forwarded to syslog |
| 11 | Info disclosure | DB or backup theft | PII column encryption (envelope, master key outside DB), TLS to DB; backups AES-256-GCM (chunked, authenticated, truncation detected) with a key kept outside the backups volume; credentials (sessions, reset tokens) excluded from backups; `make restore-test` proves restorability |
| 12 | Tampering | Supply chain | Lockfiles, `ignore-scripts`, audit gates, Trivy + OpenSCAP, SBOM, cosign verification |
| 13 | EoP | RCE through dependency or parser | No shell in images, in-process `execve` seccomp deny, rootless read-only containers, no `pickle`/`yaml.load` |
| 14 | Info disclosure / EoP | **SSRF** through an administrator-configured destination (webhook, syslog, SMTP), DNS rebinding, redirects | `https` only for URLs; every resolved address checked: loopback, link-local (`169.254.169.254`, `fd00:ec2::254`) and reserved never, private only if its network is allowlisted; connection pinned to the checked address; redirects not followed; TLS always verified; no egress route unless the overlay is used; "Send test" throttled |
| 15 | Repudiation | Local logs lost or altered after a compromise | Remote syslog over TLS (RFC 5424/5425) with bounded buffer and drop count; audit events forwarded; PII masking optional |
| 16 | Spoofing / Recon | Account guessing, scanners probing for secrets | Honeytokens (decoy usernames, trap URLs): identical answer to a failed sign-in, client IP blocked, critical audit event and notification; only attributable IPs are blocked (trusted proxy count), unblocking from the UI or CLI |
| 17 | Info disclosure | Formula injection in the audit CSV export | Cells starting with `=`, `+`, `-`, `@`, tab or CR prefixed with `'`; export requires step-up and is audited |
| 18 | Spoofing | **Forged or replayed OIDC response**: injected authorization code, stolen callback URL, login CSRF, token substitution, `alg: none` / HS256 key confusion, IdP mix-up | Code flow with PKCE (S256); `state` single use, 10 minutes, stored server-side and bound to the browser by a `SameSite=Lax` cookie; `nonce` checked in constant time; ID token signature against the JWKS with the configured asymmetric algorithm only; `iss`, `aud`, `azp`, `exp`/`iat`/`nbf` checked; RFC 9207 `iss` parameter checked; discovery `issuer` must equal the configured one |
| 19 | EoP | **Account takeover through the IdP or directory**: an external account named like a local administrator | External identities linked by `(source, external_id)` (OIDC `sub`, LDAP `entryUUID`), never by username or email; a name collision refuses the sign-in; the administrator role comes only from explicitly listed admin groups, is re-synchronized and audited at each sign-in, and still requires the wiki's second factor; provisioning can be turned off |
| 20 | EoP / Info disclosure | **LDAP injection** and unauthenticated bind | Values escaped (RFC 4515) in every filter; exactly one match required; empty passwords refused before any bind; clear-text LDAP refused (LDAPS or StartTLS before credentials), certificates verified |
| 21 | EoP | Excessive rights from groups | Group-to-space mapping explicit per space; SSO memberships marked `source = sso`, re-synchronized and audited at each sign-in; manual memberships never changed |
| 22 | DoS | IdP or directory outage locks everyone out | Local administrators with MFA keep access (break-glass); `admins_only` local sign-in raises a critical alert on each use; outages answer 503 without details |
| 23 | Tampering | Configuration drift between environment and UI | One schema validates both; environment wins and is read-only in the UI (409 on change); invalid environment stops startup; secrets only from files, write-only in the UI; every change audited |
| 24 | Info disclosure | **RAG leaks unreadable pages**: chunks, sources or answers from restricted spaces | Chunks carry `space_id`; the readable-spaces predicate, trashed pages and the current revision are filters inside the similarity query (never after the top-k); sources come from the same rows; tests check that nothing from an unreadable space reaches the prompt or the answer |
| 25 | Tampering / EoP | **Prompt injection** through page content ("ignore your instructions", forged source blocks) | Sources passed as delimited data in the user message, `<` and `>` escaped; system prompt separate and admin-controlled; no tools offered, nothing executed; the model has no more rights than the asker (it only sees what they can read) |
| 26 | Info disclosure | **Exfiltration through the answer** (remote image URLs, links) | Answers rendered with the page sanitizer: no HTML, remote images never loaded, links with real target and `rel=noopener noreferrer` |
| 27 | Info disclosure / EoP | **SSRF and model substitution** on the inference server | URL SSRF-checked (https, or http only to an allowlisted private network), proxy checked too, TLS verified with the internal CA; Ollama on an internal network, port never published; model digests pinned on approval, GGUF/safetensors only, changed model refused |
| 28 | DoS / Repudiation | Cost exhaustion; sensitive questions in logs | Per-user rate limit and daily token quota; context window and answer length capped; questions and answers not logged unless enabled (PII masking then applies); system prompt versions audited |
| 29 | Spoofing | **Stolen or leaked API key** | 32 random bytes, SHA-256 at rest, shown once, prefix for recognition; mandatory expiry (≤ 365 days, ≤ 30 with `admin`); revocation; key dead when the owner is disabled; creation needs re-authentication; last use (time, IP) shown; per-key rate limit; every call audited |
| 30 | EoP | **Tool calls beyond the owner's rights** (IDOR through ids, other spaces, admin tools) | Same services and permission checks as REST: space resolved from the key's owner, unreadable space = NOT_FOUND, page ids looked up inside that space; scopes only narrow rights; admin endpoint off by default, needs `admin` scope and an active administrator; tests enumerate tools with unauthorized keys |
| 31 | Tampering | **An AI client destroys or overwrites data** (prompt-injected agent, retries) | Destructive admin tools need explicit `confirm: true`; `update_page` needs the base `revision_id` (stale → refused); writes need an `idempotency_key` (replayed, never duplicated); no delete tool for pages |
| 32 | Spoofing | **Browser-based attacks on the MCP endpoint** (DNS rebinding, cross-site requests) | Bearer key only (no cookies); a foreign `Origin` is refused; exact Nginx locations |
