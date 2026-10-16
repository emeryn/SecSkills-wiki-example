"""MCP: API keys, scopes, permission-checked tools, admin endpoint, idempotency, audit."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update

from app.core.context import AppContext
from app.core.security import token_hash
from app.models import ApiKey, AuditEvent, AuthSession, Page, User
from app.services import api_key_service
from app.services.audit_service import SYSTEM
from tests.helpers import TestUser, make_space, make_user, sign_in, write
from tests.sso_helpers import configure

USER_TOOLS = {"search_pages", "read_page", "create_page", "update_page"}


def issue(ctx: AppContext, user: TestUser, scopes: list[str], days: int = 30) -> str:
    with ctx.sessions() as db:
        owner = db.get(User, user.id)
        assert owner is not None
        return api_key_service.issue(
            db, owner, SYSTEM, name="test", scopes=scopes, days=days
        ).secret


def rpc(
    client: TestClient,
    key: str | None,
    method: str,
    params: dict[str, Any] | None = None,
    path: str = "/mcp",
    headers: dict[str, str] | None = None,
) -> Any:
    sent = {"Content-Type": "application/json", **(headers or {})}
    if key is not None:
        sent["Authorization"] = f"Bearer {key}"
    return client.post(
        path,
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
        headers=sent,
    )


def call(
    client: TestClient, key: str, tool: str, path: str = "/mcp", **arguments: Any
) -> dict[str, Any]:
    response = rpc(client, key, "tools/call", {"name": tool, "arguments": arguments}, path)
    assert response.status_code == 200, response.text
    result: dict[str, Any] = response.json()["result"]
    return result


def error_code(result: dict[str, Any]) -> str:
    assert result["isError"] is True
    return str(result["content"][0]["text"]).split(":", 1)[0]


@pytest.fixture
def wiki(ctx: AppContext) -> dict[str, Any]:
    """Alice edits "ops"; "board" is restricted to Bob; "docs" is internal (Alice reads)."""
    alice, bob = make_user(ctx, "alice"), make_user(ctx, "bob")
    ops = make_space(ctx, "Ops", bob, members={"alice": (alice, "editor")})
    board = make_space(ctx, "Board", bob)
    docs = make_space(ctx, "Docs", bob, visibility="internal")
    with ctx.sessions() as db:
        board_home = db.scalar(select(Page.id).where(Page.slug == "board"))
    return {
        "alice": alice,
        "bob": bob,
        "ops": ops,
        "board": board,
        "docs": docs,
        "board_home": board_home,
    }


def test_handshake_and_tool_list(client: TestClient, ctx: AppContext, wiki: dict[str, Any]) -> None:
    key = issue(ctx, wiki["alice"], ["pages:read"])
    init = rpc(client, key, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}})
    assert init.json()["result"]["protocolVersion"] == "2025-06-18"
    assert init.json()["result"]["capabilities"] == {"tools": {"listChanged": False}}
    notification = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        headers={"Authorization": f"Bearer {key}"},
    )
    assert notification.status_code == 202
    tools = rpc(client, key, "tools/list").json()["result"]["tools"]
    assert {tool["name"] for tool in tools} == USER_TOOLS
    assert all(tool["inputSchema"]["type"] == "object" for tool in tools)
    assert rpc(client, key, "resources/list").json()["error"]["code"] == -32601


@pytest.mark.parametrize("path", ["/mcp", "/mcp/admin"])
def test_unauthenticated_and_invalid_keys_are_refused(
    client: TestClient, ctx: AppContext, wiki: dict[str, Any], path: str
) -> None:
    for key in (None, "wk_00000000_" + "x" * 43, "not-a-key"):
        response = rpc(client, key, "tools/list", path=path)
        assert response.status_code == 401
        assert response.headers["www-authenticate"].startswith("Bearer")
    assert client.get(path).status_code == 401


def test_revoked_and_expired_keys_stop_working(
    client: TestClient, ctx: AppContext, wiki: dict[str, Any]
) -> None:
    revoked = issue(ctx, wiki["alice"], ["pages:read"])
    expired = issue(ctx, wiki["alice"], ["pages:read"])
    assert rpc(client, revoked, "ping").status_code == 200
    with ctx.sessions() as db:
        db.execute(
            update(ApiKey)
            .where(ApiKey.key_hash == token_hash(revoked))
            .values(revoked_at=datetime.now(UTC))
        )
        db.execute(
            update(ApiKey)
            .where(ApiKey.key_hash == token_hash(expired))
            .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        db.commit()
    assert rpc(client, revoked, "ping").status_code == 401
    assert rpc(client, expired, "ping").status_code == 401


def test_disabled_owner_disables_the_key(
    client: TestClient, ctx: AppContext, wiki: dict[str, Any]
) -> None:
    key = issue(ctx, wiki["alice"], ["pages:read"])
    with ctx.sessions() as db:
        db.execute(update(User).where(User.id == wiki["alice"].id).values(status="disabled"))
        db.commit()
    assert rpc(client, key, "ping").status_code == 401


def test_secret_is_never_stored(ctx: AppContext, wiki: dict[str, Any]) -> None:
    key = issue(ctx, wiki["alice"], ["pages:read"])
    assert key.startswith("wk_") and len(key.split("_", 2)[2]) >= 43
    with ctx.sessions() as db:
        row = db.scalar(select(ApiKey))
    assert row is not None
    assert row.key_hash == token_hash(key) and key.encode() not in row.key_hash
    assert key.startswith(row.prefix + "_")


def test_scopes_narrow_the_owner_rights(
    client: TestClient, ctx: AppContext, wiki: dict[str, Any]
) -> None:
    read_only = issue(ctx, wiki["alice"], ["pages:read"])
    result = call(
        client,
        read_only,
        "create_page",
        space=wiki["ops"],
        title="X",
        idempotency_key=str(uuid.uuid4()),
    )
    assert error_code(result) == "FORBIDDEN"


def test_tools_never_reach_unreadable_spaces(
    client: TestClient, ctx: AppContext, wiki: dict[str, Any]
) -> None:
    key = issue(ctx, wiki["alice"], ["pages:read", "pages:write"])
    board, board_home = wiki["board"], wiki["board_home"]
    assert error_code(call(client, key, "read_page", space=board, slug="board")) == "NOT_FOUND"
    # A page id from another space, through a space the caller can edit.
    stolen = call(client, key, "read_page", space=wiki["ops"], page_id=str(board_home))
    assert error_code(stolen) == "NOT_FOUND"
    update_result = call(
        client,
        key,
        "update_page",
        space=wiki["ops"],
        page_id=str(board_home),
        revision_id=str(uuid.uuid4()),
        title="Pwned",
        body="x",
        idempotency_key=str(uuid.uuid4()),
    )
    assert error_code(update_result) == "NOT_FOUND"
    create_result = call(
        client, key, "create_page", space=board, title="Pwned", idempotency_key=str(uuid.uuid4())
    )
    assert error_code(create_result) == "NOT_FOUND"
    found = call(client, key, "search_pages", query="board")["structuredContent"]
    assert all(r["space"] != board for r in found["results"])
    # Read-only in an internal space.
    readonly = call(
        client, key, "create_page", space=wiki["docs"], title="X", idempotency_key=str(uuid.uuid4())
    )
    assert error_code(readonly) == "FORBIDDEN"


def test_writes_are_idempotent_and_use_if_match(
    client: TestClient, ctx: AppContext, wiki: dict[str, Any]
) -> None:
    key = issue(ctx, wiki["alice"], ["pages:read", "pages:write"])
    idem = str(uuid.uuid4())
    first = call(
        client,
        key,
        "create_page",
        space=wiki["ops"],
        title="Runbook",
        body="v1",
        idempotency_key=idem,
    )
    again = call(
        client,
        key,
        "create_page",
        space=wiki["ops"],
        title="Runbook",
        body="v1",
        idempotency_key=idem,
    )
    assert first["structuredContent"] == again["structuredContent"]
    with ctx.sessions() as db:
        assert db.scalar(select(func.count()).where(Page.title == "Runbook")) == 1
    reused = call(
        client, key, "create_page", space=wiki["ops"], title="Other", idempotency_key=idem
    )
    assert error_code(reused) == "IDEMPOTENCY_KEY_REUSED"

    page = first["structuredContent"]
    missing = call(
        client,
        key,
        "update_page",
        space=wiki["ops"],
        page_id=page["page_id"],
        title="Runbook",
        body="v2",
        idempotency_key=str(uuid.uuid4()),
    )
    assert error_code(missing) == "INVALID_ARGUMENTS"
    updated = call(
        client,
        key,
        "update_page",
        space=wiki["ops"],
        page_id=page["page_id"],
        revision_id=page["revision_id"],
        title="Runbook",
        body="v2",
        idempotency_key=str(uuid.uuid4()),
    )
    assert updated["structuredContent"]["body"] == "v2"
    stale = call(
        client,
        key,
        "update_page",
        space=wiki["ops"],
        page_id=page["page_id"],
        revision_id=page["revision_id"],
        title="Runbook",
        body="v3",
        idempotency_key=str(uuid.uuid4()),
    )
    assert error_code(stale) == "STALE_REVISION"


def test_every_tool_call_is_audited_with_masked_arguments(
    client: TestClient, ctx: AppContext, wiki: dict[str, Any]
) -> None:
    key = issue(ctx, wiki["alice"], ["pages:read", "pages:write"])
    secret_body = "TOP SECRET CONTENT " * 10
    call(client, key, "search_pages", query="anything")
    call(
        client,
        key,
        "create_page",
        space=wiki["ops"],
        title="Note",
        body=secret_body,
        idempotency_key=str(uuid.uuid4()),
    )
    call(client, key, "read_page", space=wiki["board"], slug="board")
    rpc(client, key, "tools/call", {"name": "no_such_tool", "arguments": {}})
    with ctx.sessions() as db:
        events = db.scalars(
            select(AuditEvent).where(AuditEvent.action == "mcp.tool_call").order_by(AuditEvent.id)
        ).all()
    assert [e.after["tool"] for e in events if e.after] == [
        "search_pages",
        "create_page",
        "read_page",
        "no_such_tool",
    ]
    assert [e.outcome for e in events] == ["success", "success", "failure", "failure"]
    assert all(e.actor_user_id == wiki["alice"].id and e.target_type == "api_key" for e in events)
    assert "TOP SECRET" not in str(events[1].after)
    assert events[1].after is not None and events[1].after["arguments"]["body"].startswith("<")
    assert all(isinstance(e.after["duration_ms"], int) for e in events if e.after)


def test_foreign_origin_is_refused(
    client: TestClient, ctx: AppContext, wiki: dict[str, Any]
) -> None:
    key = issue(ctx, wiki["alice"], ["pages:read"])
    refused = rpc(client, key, "ping", headers={"Origin": "https://evil.example.com"})
    assert refused.status_code == 403
    allowed = rpc(client, key, "ping", headers={"Origin": "https://testserver"})
    assert allowed.status_code == 200


def test_per_key_rate_limit(client: TestClient, ctx: AppContext, wiki: dict[str, Any]) -> None:
    configure(ctx, "mcp", requests_per_minute=2)
    key = issue(ctx, wiki["alice"], ["pages:read"])
    assert [rpc(client, key, "ping").status_code for _ in range(3)] == [200, 200, 429]


def test_admin_endpoint_is_off_by_default_and_needs_admin_scope(
    client: TestClient, ctx: AppContext, wiki: dict[str, Any]
) -> None:
    root = make_user(ctx, "root", role="admin")
    admin_key = issue(ctx, root, ["admin"])
    user_key = issue(ctx, wiki["alice"], ["pages:read"])
    assert rpc(client, admin_key, "tools/list", path="/mcp/admin").status_code == 404
    configure(ctx, "mcp", admin_enabled=True)
    assert rpc(client, user_key, "tools/list", path="/mcp/admin").status_code == 403
    root_reader = issue(ctx, root, ["pages:read"])
    assert rpc(client, root_reader, "tools/list", path="/mcp/admin").status_code == 403
    tools = rpc(client, admin_key, "tools/list", path="/mcp/admin").json()["result"]["tools"]
    destructive = {t["name"] for t in tools if t["annotations"]["destructiveHint"]}
    assert destructive == {"unblock_ip", "revoke_user_sessions"}
    # Admin keys are capped at 30 days.
    with ctx.sessions() as db:
        expires = db.scalar(
            select(ApiKey.expires_at).where(ApiKey.key_hash == token_hash(admin_key))
        )
    assert expires is not None and expires < datetime.now(UTC) + timedelta(days=31)


def test_destructive_admin_tools_need_confirm(
    client: TestClient, ctx: AppContext, wiki: dict[str, Any]
) -> None:
    configure(ctx, "mcp", admin_enabled=True)
    key = issue(ctx, make_user(ctx, "root", role="admin"), ["admin"])
    target = str(wiki["alice"].id)
    refused = call(client, key, "revoke_user_sessions", "/mcp/admin", user_id=target)
    assert error_code(refused) == "CONFIRMATION_REQUIRED"
    done = call(client, key, "revoke_user_sessions", "/mcp/admin", user_id=target, confirm=True)
    assert done["isError"] is False
    users = call(client, key, "list_users", "/mcp/admin")["structuredContent"]["users"]
    assert {"alice", "bob", "root"} <= {u["username"] for u in users}


def test_key_management_needs_recent_auth_and_admin_scope_needs_admin(
    client: TestClient, ctx: AppContext, wiki: dict[str, Any]
) -> None:
    sign_in(client, wiki["alice"])
    created = write(
        client, "POST", "/api/v1/me/api-keys", json={"name": "laptop", "scopes": ["pages:read"]}
    )
    assert created.status_code == 201, created.text
    assert created.json()["secret"].startswith(created.json()["prefix"])
    listed = client.get("/api/v1/me/api-keys").json()
    assert "secret" not in listed[0] and listed[0]["status"] == "active"
    admin_scope = write(
        client, "POST", "/api/v1/me/api-keys", json={"name": "x", "scopes": ["admin"]}
    )
    assert admin_scope.status_code == 403
    revoked = write(client, "DELETE", f"/api/v1/me/api-keys/{created.json()['id']}")
    assert revoked.status_code == 204
    other = issue(ctx, wiki["bob"], ["pages:read"])
    with ctx.sessions() as db:
        bob_key = db.scalar(select(ApiKey.id).where(ApiKey.key_hash == token_hash(other)))
    assert write(client, "DELETE", f"/api/v1/me/api-keys/{bob_key}").status_code == 404
    with ctx.sessions() as db:
        db.execute(update(AuthSession).values(reauth_at=None))
        db.commit()
    stale = write(
        client, "POST", "/api/v1/me/api-keys", json={"name": "y", "scopes": ["pages:read"]}
    )
    assert stale.json()["error"]["code"] == "REAUTH_REQUIRED"
