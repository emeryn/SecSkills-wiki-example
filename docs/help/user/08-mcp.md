# AI assistants (MCP)

AI assistants and tools that speak the Model Context Protocol (MCP) can search, read, create and
update wiki pages for you, with your rights and never more.

1. **Account > API keys > New key**: give it a name, the smallest scopes the tool needs
   (`pages:read` to search and read, `pages:write` to create and edit) and an expiry.
2. Copy the key: it is shown once.
3. In the assistant, add an MCP server of type *Streamable HTTP*:
   - URL: `<wiki address>/mcp`, for example `https://wiki.example.com/mcp`
   - Header: `Authorization: Bearer <your key>`

Tools: `search_pages`, `read_page`, `create_page` and `update_page`. An update must name the
revision it starts from: if someone else saved the page meanwhile, it is refused instead of
overwriting their work.

Revoke a key as soon as a tool no longer needs it, or if it may have leaked. Every call made with
a key is recorded in the audit log.
