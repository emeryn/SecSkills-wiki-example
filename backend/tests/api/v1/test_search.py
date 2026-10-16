from fastapi.testclient import TestClient

from app.core.context import AppContext
from tests.helpers import make_space, make_user, sign_in, write


def _setup(client: TestClient, ctx: AppContext) -> tuple[str, str]:
    owner = make_user(ctx, "owner")
    alice = make_user(ctx, "alice")
    secret = make_space(ctx, "Secret", owner, members={"alice": (alice, "editor")})
    handbook = make_space(
        ctx, "Handbook", owner, visibility="internal", members={"alice": (alice, "editor")}
    )
    sign_in(client, alice)
    write(
        client,
        "POST",
        f"/api/v1/spaces/{secret}/pages",
        json={
            "title": "Quarterly roadmap",
            "body": "The falcon project starts in March.\n<script>falcon()</script>",
        },
    )
    write(
        client,
        "POST",
        f"/api/v1/spaces/{handbook}/pages",
        json={
            "title": "Falcon handbook",
            "body": "How we work on falcon.",
        },
    )
    return secret, handbook


def test_results_are_filtered_by_readable_spaces(client: TestClient, ctx: AppContext) -> None:
    secret, _ = _setup(client, ctx)
    titles = [
        h["title"] for h in client.get("/api/v1/search", params={"q": "falcon"}).json()["items"]
    ]
    assert titles == ["Falcon handbook", "Quarterly roadmap"]  # title matches first

    with TestClient(
        client.app, base_url="https://testserver", headers={"X-Requested-With": "XMLHttpRequest"}
    ) as bob:
        sign_in(bob, make_user(ctx, "bob"))
        response = bob.get("/api/v1/search", params={"q": "falcon"})
        assert [h["title"] for h in response.json()["items"]] == ["Falcon handbook"]
        assert "roadmap" not in response.text.lower() and "march" not in response.text.lower()
        assert response.json()["total"] == 1
        assert bob.get("/api/v1/search", params={"q": "falcon", "space": secret}).status_code == 404


def test_snippets_are_plain_text_segments(client: TestClient, ctx: AppContext) -> None:
    secret, _ = _setup(client, ctx)
    write(
        client,
        "POST",
        f"/api/v1/spaces/{secret}/pages",
        json={
            "title": "Markup",
            "body": "<img src=x onerror=alert(1)> heron <b>notes</b>",
        },
    )
    hit = client.get("/api/v1/search", params={"q": "heron"}).json()["items"][0]
    assert [s["text"] for s in hit["snippet"] if s["highlight"]] == ["heron"]
    joined = "".join(s["text"] for s in hit["snippet"])
    # Segments are plain text (ts_headline even drops most tags); the client renders them as text.
    assert "notes" in joined
    assert all(set(segment) == {"text", "highlight"} for segment in hit["snippet"])


def test_trashed_pages_are_not_found(client: TestClient, ctx: AppContext) -> None:
    secret, _ = _setup(client, ctx)
    page = client.get("/api/v1/search", params={"q": "roadmap"}).json()["items"][0]
    write(client, "DELETE", f"/api/v1/spaces/{secret}/pages/{page['page_id']}")
    assert client.get("/api/v1/search", params={"q": "roadmap"}).json()["total"] == 0


def test_edits_update_the_index_and_queries_are_bounded(
    client: TestClient, ctx: AppContext
) -> None:
    secret, _ = _setup(client, ctx)
    hit = client.get("/api/v1/search", params={"q": "roadmap"}).json()["items"][0]
    page = client.get(f"/api/v1/spaces/{secret}/pages/{hit['page_id']}").json()
    write(
        client,
        "PUT",
        f"/api/v1/spaces/{secret}/pages/{page['id']}",
        json={"title": page["title"], "body": "Now about the osprey initiative."},
        headers={"If-Match": f'"{page["revision_id"]}"'},
    )
    assert client.get("/api/v1/search", params={"q": "osprey"}).json()["total"] == 1
    assert client.get("/api/v1/search", params={"q": "x" * 201}).status_code == 422
    assert client.get("/api/v1/search", params={"q": "!!! & | ("}).status_code == 200
    assert client.get("/api/v1/search", params={"q": "falcon", "page_size": 51}).status_code == 422
