"""Space-level authorization and "no title leak" guarantees of the specification."""

import re
import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.context import AppContext
from app.core.permissions import route_policies
from app.models import Group, GroupMember, Page, SpaceMember
from app.repositories import spaces as space_repo
from tests.helpers import make_space, make_user, sign_in, write


def _client(client: TestClient) -> TestClient:
    return TestClient(
        client.app, base_url="https://testserver", headers={"X-Requested-With": "XMLHttpRequest"}
    )


def _space_routes(app: FastAPI) -> list[tuple[str, str]]:
    return sorted(k for k in route_policies(app) if "/spaces/{space}" in k[1])


def _home(ctx: AppContext, key: str) -> uuid.UUID:
    with ctx.sessions() as db:
        space = space_repo.get_by_key(db, key)
        assert space is not None and space.home_page_id is not None
        return space.home_page_id


def test_restricted_space_does_not_exist_for_outsiders(
    app: FastAPI, client: TestClient, ctx: AppContext
) -> None:
    owner = make_user(ctx, "owner")
    key = make_space(ctx, "Secret Project", owner)
    home = _home(ctx, key)
    sign_in(client, make_user(ctx, "mallory"))
    routes = _space_routes(app)
    assert len(routes) >= 15
    for method, path in routes:
        url = path.replace("{space}", key)
        url = re.sub(r"\{(page_id)\}", str(home), url)
        url = re.sub(r"\{[^}]+\}", str(uuid.uuid4()), url).replace("{slug}", "home")
        response = write(client, method, url, json={})
        assert response.status_code == 404, f"{method} {path} -> {response.status_code}"
        assert "Secret" not in response.text


def test_viewer_cannot_write(client: TestClient, ctx: AppContext) -> None:
    owner = make_user(ctx, "owner")
    viewer = make_user(ctx, "vera")
    key = make_space(ctx, "Docs", owner, members={"vera": (viewer, "viewer")})
    sign_in(client, viewer)
    home = _home(ctx, key)
    assert client.get(f"/api/v1/spaces/{key}/pages/{home}").status_code == 200
    assert (
        write(client, "POST", f"/api/v1/spaces/{key}/pages", json={"title": "x"}).status_code == 403
    )
    assert write(client, "DELETE", f"/api/v1/spaces/{key}/pages/{home}").status_code == 403
    assert client.get(f"/api/v1/spaces/{key}/members").status_code == 403


def test_internal_space_is_readable_by_everyone_but_not_writable(
    client: TestClient, ctx: AppContext
) -> None:
    owner = make_user(ctx, "owner")
    key = make_space(ctx, "Handbook", owner, visibility="internal")
    sign_in(client, make_user(ctx, "newcomer"))
    assert [s["key"] for s in client.get("/api/v1/spaces").json()] == [key]
    assert client.get(f"/api/v1/spaces/{key}/pages").status_code == 200
    assert (
        write(client, "POST", f"/api/v1/spaces/{key}/pages", json={"title": "x"}).status_code == 403
    )


def test_admin_manages_but_cannot_read_restricted_space(
    client: TestClient, ctx: AppContext
) -> None:
    owner = make_user(ctx, "owner")
    key = make_space(ctx, "HR", owner)
    sign_in(client, make_user(ctx, "root", role="admin"))
    assert client.get(f"/api/v1/spaces/{key}").status_code == 200
    assert client.get(f"/api/v1/spaces/{key}/members").status_code == 200
    assert client.get(f"/api/v1/spaces/{key}/pages").status_code == 404
    assert client.get(f"/api/v1/spaces/{key}/pages/{_home(ctx, key)}").status_code == 404
    assert key in [s["key"] for s in client.get("/api/v1/admin/spaces").json()]
    assert key not in [s["key"] for s in client.get("/api/v1/spaces").json()]


def test_recent_changes_and_favorites_never_reveal_unreadable_titles(
    client: TestClient, ctx: AppContext
) -> None:
    owner = make_user(ctx, "owner")
    alice = make_user(ctx, "alice")
    secret = make_space(ctx, "Secret Plans", owner, members={"alice": (alice, "editor")})
    public = make_space(ctx, "Public Handbook", owner, visibility="internal")
    sign_in(client, alice)
    page = write(
        client, "POST", f"/api/v1/spaces/{secret}/pages", json={"title": "Acquisition target"}
    ).json()
    assert write(client, "PUT", f"/api/v1/me/favorites/{page['id']}").status_code == 204
    titles = [c["title"] for c in client.get("/api/v1/recent-changes").json()]
    assert "Acquisition target" in titles and "Public Handbook" in titles

    with _client(client) as bob:
        sign_in(bob, make_user(ctx, "bob"))
        feed = bob.get("/api/v1/recent-changes").text
        assert "Acquisition" not in feed and "Secret Plans" not in feed
        assert "Public Handbook" in feed
        assert bob.get("/api/v1/recent-changes", params={"space": secret}).status_code == 404
        assert write(bob, "PUT", f"/api/v1/me/favorites/{page['id']}").status_code == 404

    with ctx.sessions() as db:
        space = space_repo.get_by_key(db, secret)
        assert space is not None
        member = db.get(SpaceMember, (space.id, "user", alice.id))
        db.delete(member)
        db.commit()
    assert client.get("/api/v1/me/favorites").json() == []
    assert "Acquisition" not in client.get("/api/v1/recent-changes").text
    assert public  # internal space still listed for alice
    assert [s["key"] for s in client.get("/api/v1/spaces").json()] == [public]


def test_group_membership_grants_access_until_group_deleted(
    client: TestClient, ctx: AppContext
) -> None:
    owner = make_user(ctx, "owner")
    dana = make_user(ctx, "dana")
    key = make_space(ctx, "Ops", owner)
    with ctx.sessions() as db:
        group = Group(id=uuid.uuid4(), name="Operators", description="", source="local")
        db.add(group)
        db.flush()
        db.add(GroupMember(group_id=group.id, user_id=dana.id))
        space = space_repo.get_by_key(db, key)
        assert space is not None
        db.add(
            SpaceMember(
                space_id=space.id, principal_type="group", principal_id=group.id, role="editor"
            )
        )
        db.commit()
        group_id = group.id
    sign_in(client, dana)
    assert (
        write(client, "POST", f"/api/v1/spaces/{key}/pages", json={"title": "Runbook"}).status_code
        == 201
    )
    with _client(client) as admin:
        sign_in(admin, make_user(ctx, "root", role="admin"))
        assert write(admin, "DELETE", f"/api/v1/admin/groups/{group_id}").status_code == 204
    assert client.get(f"/api/v1/spaces/{key}/pages").status_code == 404


def test_membership_changes_are_audited_and_last_space_admin_kept(
    client: TestClient, ctx: AppContext
) -> None:
    owner = make_user(ctx, "owner")
    vera = make_user(ctx, "vera")
    key = make_space(ctx, "Docs", owner)
    sign_in(client, owner)
    url = f"/api/v1/spaces/{key}/members/user"
    assert write(client, "PUT", f"{url}/{vera.id}", json={"role": "viewer"}).status_code == 204
    assert write(client, "PUT", f"{url}/{vera.id}", json={"role": "owner"}).status_code == 422
    assert write(client, "DELETE", f"{url}/{owner.id}").status_code == 409
    members = client.get(f"/api/v1/spaces/{key}/members").json()
    assert {(m["name"], m["role"]) for m in members} == {
        ("owner", "space_admin"),
        ("vera", "viewer"),
    }
    from app.models import AuditEvent  # noqa: PLC0415

    with ctx.sessions() as db:
        assert "space.member_set" in db.scalars(select(AuditEvent.action)).all()


def test_rendered_titles_are_stored_raw_never_as_html(client: TestClient, ctx: AppContext) -> None:
    owner = make_user(ctx, "owner")
    key = make_space(ctx, "Docs", owner)
    sign_in(client, owner)
    page = write(
        client,
        "POST",
        f"/api/v1/spaces/{key}/pages",
        json={"title": "<img src=x onerror=alert(1)>", "body": "<script>alert(1)</script>"},
    ).json()
    assert page["title"] == "<img src=x onerror=alert(1)>"
    assert page["body"] == "<script>alert(1)</script>"
    assert (
        client.get(f"/api/v1/spaces/{key}/pages/{page['id']}").headers["content-type"]
        == "application/json"
    )
    with ctx.sessions() as db:
        assert (
            db.scalar(select(Page.slug).where(Page.id == uuid.UUID(page["id"])))
            == "img-src-x-onerror-alert-1"
        )


def test_principal_search_is_limited_to_space_managers(client: TestClient, ctx: AppContext) -> None:
    owner = make_user(ctx, "owner")
    viewer = make_user(ctx, "vera")
    make_user(ctx, "victor")
    key = make_space(ctx, "Docs", owner, members={"vera": (viewer, "viewer")})
    sign_in(client, viewer)
    assert client.get(f"/api/v1/spaces/{key}/principals", params={"q": "vi"}).status_code == 403
    with _client(client) as manager:
        sign_in(manager, owner)
        found = manager.get(f"/api/v1/spaces/{key}/principals", params={"q": "vi"}).json()
        assert [p["name"] for p in found] == ["victor"]
