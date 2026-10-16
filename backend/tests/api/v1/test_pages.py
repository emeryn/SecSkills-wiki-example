from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.context import AppContext
from app.models import AuditEvent
from tests.helpers import TestUser, make_space, make_user, sign_in, write


@pytest.fixture
def editor(ctx: AppContext) -> TestUser:
    return make_user(ctx, "erin")


@pytest.fixture
def space(ctx: AppContext, editor: TestUser) -> str:
    owner = make_user(ctx, "owner")
    return make_space(ctx, "Engineering Docs", owner, members={"erin": (editor, "editor")})


@pytest.fixture
def as_editor(client: TestClient, editor: TestUser, space: str) -> Iterator[TestClient]:
    sign_in(client, editor)
    yield client


def create(client: TestClient, space: str, title: str, **extra: object) -> dict[str, object]:
    response = write(
        client, "POST", f"/api/v1/spaces/{space}/pages", json={"title": title, **extra}
    )
    assert response.status_code == 201, response.text
    body: dict[str, object] = response.json()
    return body


def put(client: TestClient, space: str, page: dict[str, object], **changes: object) -> object:
    body = {"title": page["title"], "body": page["body"], **changes}
    headers = {"If-Match": f'"{page["revision_id"]}"'}
    return write(
        client, "PUT", f"/api/v1/spaces/{space}/pages/{page['id']}", json=body, headers=headers
    )


def test_space_has_key_and_home_page(as_editor: TestClient, space: str) -> None:
    assert space == "engineering-docs"
    info = as_editor.get(f"/api/v1/spaces/{space}").json()
    assert info["role"] == "editor"
    tree = as_editor.get(f"/api/v1/spaces/{space}/pages").json()
    assert [n["title"] for n in tree] == ["Engineering Docs"]
    assert tree[0]["id"] == info["home_page_id"]


def test_slugs_are_generated_server_side(as_editor: TestClient, space: str) -> None:
    page = create(as_editor, space, "Héllo Wörld / ../../etc?x=1")
    assert page["slug"] == "hello-world-etc-x-1"
    second = create(as_editor, space, "Hello world: etc x 1")
    assert second["slug"] == "hello-world-etc-x-1-2"
    long_page = create(as_editor, space, "a" * 200)
    assert len(str(long_page["slug"])) <= 80
    found = as_editor.get(f"/api/v1/spaces/{space}/pages/by-slug/{page['slug']}")
    assert found.json()["id"] == page["id"]


def test_titles_are_unique_per_space_and_bounded(as_editor: TestClient, space: str) -> None:
    create(as_editor, space, "Runbook")
    duplicate = write(
        as_editor, "POST", f"/api/v1/spaces/{space}/pages", json={"title": "  RUNBOOK "}
    )
    assert duplicate.status_code == 409
    too_long = write(as_editor, "POST", f"/api/v1/spaces/{space}/pages", json={"title": "x" * 201})
    assert too_long.status_code == 422
    newline = write(as_editor, "POST", f"/api/v1/spaces/{space}/pages", json={"title": "a\nb"})
    assert newline.status_code == 422


def test_body_limit_is_one_megabyte(as_editor: TestClient, space: str) -> None:
    response = write(
        as_editor,
        "POST",
        f"/api/v1/spaces/{space}/pages",
        json={"title": "Big", "body": "x" * 1_000_001},
    )
    assert response.status_code in (413, 422)


def test_optimistic_locking(as_editor: TestClient, space: str) -> None:
    page = create(as_editor, space, "Design", body="v1")
    missing = write(
        as_editor,
        "PUT",
        f"/api/v1/spaces/{space}/pages/{page['id']}",
        json={"title": "Design", "body": "x"},
    )
    assert missing.status_code == 428

    saved = put(as_editor, space, page, body="v2", message="second")
    assert saved.status_code == 200  # type: ignore[attr-defined]
    assert saved.json()["revision_number"] == 2  # type: ignore[attr-defined]
    assert saved.headers["etag"] == f'"{saved.json()["revision_id"]}"'  # type: ignore[attr-defined]

    stale = put(as_editor, space, page, body="v2-from-someone-else")
    assert stale.status_code == 412  # type: ignore[attr-defined]
    details = stale.json()["error"]["details"]  # type: ignore[attr-defined]
    assert details["current_number"] == 2
    assert details["author"] == "erin"


def test_saving_identical_content_creates_no_revision(as_editor: TestClient, space: str) -> None:
    page = create(as_editor, space, "Same", body="text")
    response = put(as_editor, space, page)
    assert response.json()["revision_number"] == 1  # type: ignore[attr-defined]


def test_depth_is_limited_to_five(as_editor: TestClient, space: str) -> None:
    parent = None
    for level in range(1, 6):
        page = create(as_editor, space, f"Level {level}", parent_id=parent)
        parent = page["id"]
    deeper = write(
        as_editor,
        "POST",
        f"/api/v1/spaces/{space}/pages",
        json={"title": "Level 6", "parent_id": parent},
    )
    assert deeper.status_code == 422
    assert deeper.json()["error"]["code"] == "MAX_DEPTH"


def test_move_reorders_and_refuses_cycles(as_editor: TestClient, space: str) -> None:
    a = create(as_editor, space, "A")
    b = create(as_editor, space, "B")
    child = create(as_editor, space, "A child", parent_id=a["id"])
    moved = write(
        as_editor,
        "POST",
        f"/api/v1/spaces/{space}/pages/{b['id']}/move",
        json={"parent_id": None, "position": 0},
    )
    assert moved.status_code == 200
    roots = [
        n for n in as_editor.get(f"/api/v1/spaces/{space}/pages").json() if n["parent_id"] is None
    ]
    first = min(roots, key=lambda n: n["position"])
    assert first["title"] == "B"
    cycle = write(
        as_editor,
        "POST",
        f"/api/v1/spaces/{space}/pages/{a['id']}/move",
        json={"parent_id": child["id"], "position": 0},
    )
    assert cycle.status_code == 422


def test_trash_subtree_restore_and_home_protection(
    as_editor: TestClient, space: str, ctx: AppContext
) -> None:
    parent = create(as_editor, space, "Parent")
    create(as_editor, space, "Child", parent_id=parent["id"])
    assert (
        write(as_editor, "DELETE", f"/api/v1/spaces/{space}/pages/{parent['id']}").status_code
        == 204
    )
    titles = [n["title"] for n in as_editor.get(f"/api/v1/spaces/{space}/pages").json()]
    assert "Parent" not in titles and "Child" not in titles
    trash = as_editor.get(f"/api/v1/spaces/{space}/trash").json()
    assert [(t["title"], t["pages"]) for t in trash] == [("Parent", 2)]
    assert as_editor.get(f"/api/v1/spaces/{space}/pages/{parent['id']}").status_code == 404

    restored = write(as_editor, "POST", f"/api/v1/spaces/{space}/trash/{parent['id']}/restore")
    assert restored.status_code == 200
    titles = [n["title"] for n in as_editor.get(f"/api/v1/spaces/{space}/pages").json()]
    assert {"Parent", "Child"} <= set(titles)

    home = as_editor.get(f"/api/v1/spaces/{space}").json()["home_page_id"]
    assert write(as_editor, "DELETE", f"/api/v1/spaces/{space}/pages/{home}").status_code == 409
    with ctx.sessions() as db:
        actions = db.scalars(select(AuditEvent.action)).all()
    assert "page.deleted" in actions and "page.restored" in actions


def test_only_space_admins_purge_trash(as_editor: TestClient, space: str) -> None:
    page = create(as_editor, space, "Temp")
    write(as_editor, "DELETE", f"/api/v1/spaces/{space}/pages/{page['id']}")
    assert (
        write(as_editor, "DELETE", f"/api/v1/spaces/{space}/trash/{page['id']}").status_code == 403
    )


def test_revisions_diff_and_restore(as_editor: TestClient, space: str, ctx: AppContext) -> None:
    page = create(as_editor, space, "Notes", body="line one\nline two")
    second = put(as_editor, space, page, body="line one\nline 2\nline three").json()  # type: ignore[attr-defined]
    history = as_editor.get(f"/api/v1/spaces/{space}/pages/{page['id']}/revisions").json()
    assert [r["number"] for r in history["items"]] == [2, 1]
    first_id = history["items"][1]["id"]

    diff = as_editor.get(
        f"/api/v1/spaces/{space}/pages/{page['id']}/revisions/{second['revision_id']}/diff",
        params={"against": first_id},
    ).json()
    ops = [(line["op"], line["text"]) for line in diff["lines"] if line["op"] != "equal"]
    assert ops == [("delete", "line two"), ("insert", "line 2"), ("insert", "line three")]

    restored = write(
        as_editor, "POST", f"/api/v1/spaces/{space}/pages/{page['id']}/revisions/{first_id}/restore"
    )
    assert restored.json()["revision_number"] == 3
    assert restored.json()["body"] == "line one\nline two"
    with ctx.sessions() as db:
        assert "revision.restored" in db.scalars(select(AuditEvent.action)).all()


def test_archived_space_is_read_only(client: TestClient, ctx: AppContext, editor: TestUser) -> None:
    owner = make_user(ctx, "owner2")
    key = make_space(ctx, "Old", owner, members={"erin": (editor, "editor")})
    sign_in(client, owner)
    assert write(client, "DELETE", f"/api/v1/spaces/{key}").status_code == 204
    with TestClient(
        client.app, base_url="https://testserver", headers={"X-Requested-With": "XMLHttpRequest"}
    ) as other:
        sign_in(other, editor)
        assert other.get(f"/api/v1/spaces/{key}/pages").status_code == 200
        response = write(other, "POST", f"/api/v1/spaces/{key}/pages", json={"title": "New"})
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "SPACE_ARCHIVED"
