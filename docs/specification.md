# Specification: Wiki

Copy this file to `docs/specification.md` in the new project. It describes *what* to build; the skills describe *how*.

## Goal
A self-hosted, offline-capable internal wiki where teams write and organize Markdown pages, with history, search and access control.

## Users & Roles
| Role | Scope | Can |
|---|---|---|
| Viewer | Space | Read pages and attachments |
| Editor | Space | Viewer + create, edit, move, delete pages, upload attachments |
| Space admin | Space | Editor + manage space members and settings |
| Admin | Global | Manage users, groups, spaces, settings, audit; no implicit read access to restricted spaces unless member |

## Functional Scope (v1)
- **Spaces:** create, rename, archive. Visibility `restricted` (members only) or `internal` (all authenticated users read).
- **Pages:** title, slug, Markdown body, parent page (tree, max depth 5), position among siblings.
- **Editor:** split view Markdown / preview, toolbar (headings, bold, list, link, code, table), `Ctrl+S` to save, unsaved-changes warning.
- **Internal links:** `[[Page title]]` resolved within the space; broken links highlighted.
- **Revisions:** every save creates a revision (author, date, optional message). View history, diff two revisions, restore a revision.
- **Concurrent editing:** optimistic locking. `PUT` sends `If-Match: <revision_id>`; a stale revision returns `412` and the UI shows a diff to merge.
- **Trash:** deleted pages go to a per-space trash for 30 days, restorable by editors, purged by a scheduled job.
- **Search:** full-text across readable pages (PostgreSQL `tsvector`, GIN index), results filtered by permissions in SQL, title matches first, highlighted snippets.
- **Attachments:** images and documents (PDF, Office, text), max 10 MB, per page. Images embeddable in Markdown.
- **Export:** a page or a whole space as Markdown (zip).
- **Recent changes:** per space and global feed of the pages the user can read.
- **Favorites:** users star pages; favorites shown in the sidebar.

## Out of Scope (v1)
Real-time co-editing, comments, public (anonymous) access, WYSIWYG editor, Mermaid/diagrams, email digests.

## Optional Extensions
- **SSO:** OIDC and LDAPS with group-to-space-role mapping, configurable from the admin UI or environment variables.
- **Ask the wiki:** RAG over readable pages with a local LLM (`offline-llm-orchestrator`).
- **MCP:** tools `search_pages`, `read_page`, `create_page`, `update_page` bound to the caller's permissions.

## Pages (UI)
| Route | Page type |
|---|---|
| `/` | Dashboard: favorites, recent changes, my spaces |
| `/spaces` | List |
| `/spaces/:space` | Detail: page tree in the sidebar, space home page |
| `/spaces/:space/pages/:slug` | Detail: rendered page, actions (edit, history, move, delete, export) |
| `/spaces/:space/pages/:slug/edit` | Form: editor |
| `/spaces/:space/pages/:slug/history` | List + diff view |
| `/search?q=` | List |
| `/admin/*` | Users, groups, spaces, settings, audit, dashboard |

## API (v1)
| Method | Path | Permission |
|---|---|---|
| GET/POST | `/api/v1/spaces` | authenticated / admin |
| GET/PATCH/DELETE | `/api/v1/spaces/{space}` | viewer / space admin / admin |
| GET/PUT/DELETE | `/api/v1/spaces/{space}/members` | space admin |
| GET/POST | `/api/v1/spaces/{space}/pages` | viewer / editor |
| GET/PUT/DELETE | `/api/v1/spaces/{space}/pages/{page_id}` | viewer / editor / editor |
| POST | `/api/v1/spaces/{space}/pages/{page_id}/move` | editor |
| GET | `/api/v1/spaces/{space}/pages/{page_id}/revisions` | viewer |
| GET | `/api/v1/spaces/{space}/pages/{page_id}/revisions/{rev}/diff?against=` | viewer |
| POST | `/api/v1/spaces/{space}/pages/{page_id}/revisions/{rev}/restore` | editor |
| GET/POST | `/api/v1/spaces/{space}/pages/{page_id}/attachments` | viewer / editor |
| GET/DELETE | `/api/v1/attachments/{id}` | viewer / editor |
| GET/POST | `/api/v1/spaces/{space}/trash`, `/trash/{page_id}/restore` | editor |
| GET | `/api/v1/search?q=` | authenticated |
| GET | `/api/v1/spaces/{space}/export` | viewer |
| GET | `/api/v1/recent-changes` | authenticated |
| GET/PUT/DELETE | `/api/v1/me/favorites/{page_id}` | authenticated |

## Wiki-specific Security Requirements
- **Stored XSS is the primary risk:** Markdown is stored raw and rendered with HTML disabled (`markdown-it` `html: false`) then sanitized with DOMPurify. Links with `javascript:`/`data:` schemes are dropped. External links open with `rel="noopener noreferrer"`.
- Remote images are not loaded; only attachments from the same origin.
- Attachments served from `/api/v1/attachments/{id}` with `Content-Disposition: attachment` (inline only for re-encoded raster images), never from the static web root. SVG and HTML refused.
- Search, recent changes, exports, favorites and link resolution never reveal titles of pages the user cannot read.
- Slugs are generated server-side (`[a-z0-9-]`, max 80 chars); no user-controlled file paths.
- Page body max 1 MB, title max 200 chars, revision message max 500 chars.
- Exports are generated in a temp directory with sanitized file names (zip-slip safe).
- Audit: space membership changes, page deletion/restore, revision restore, exports, permission changes.

## Data Model (indicative)
`users`, `groups`, `group_members`, `spaces`, `space_members (space_id, principal_type, principal_id, role)`, `pages (id, space_id, parent_id, slug, title, current_revision_id, position, deleted_at)`, `revisions (id, page_id, author_id, body, message, created_at)`, `attachments`, `favorites`, `audit_events`, `sessions`, `idempotency_keys`.
