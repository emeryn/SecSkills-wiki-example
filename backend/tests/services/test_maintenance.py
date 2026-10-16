import uuid
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import func, select, update

from app.core.context import AppContext
from app.models import AuthSession, BlockedIp, IdempotencyKey, Page, ServerError
from app.services import maintenance
from tests.helpers import make_space, make_user, sign_in, write


def test_purge_removes_only_expired_sessions(client: TestClient, ctx: AppContext) -> None:
    bob = make_user(ctx, "bob")
    sign_in(client, bob)
    with TestClient(
        client.app, base_url="https://testserver", headers={"X-Requested-With": "XMLHttpRequest"}
    ) as other:
        sign_in(other, bob)
    with ctx.sessions() as db:
        oldest = db.scalar(select(AuthSession.id).order_by(AuthSession.created_at).limit(1))
        db.execute(
            update(AuthSession)
            .where(AuthSession.id == oldest)
            .values(revoked_at=datetime.now(UTC) - timedelta(days=2))
        )
        db.commit()
        counts = maintenance.purge_expired(db)
        assert counts["sessions"] == 1
        assert db.scalar(select(func.count()).select_from(AuthSession)) == 1


def _trash(client: TestClient, space: str, title: str) -> str:
    created = write(client, "POST", f"/api/v1/spaces/{space}/pages", json={"title": title})
    assert created.status_code == 201, created.text
    page_id = str(created.json()["id"])
    assert write(client, "DELETE", f"/api/v1/spaces/{space}/pages/{page_id}").status_code == 204
    return page_id


def test_purge_leaves_non_expired_data(client: TestClient, ctx: AppContext) -> None:
    owner = make_user(ctx, "owner")
    space = make_space(ctx, "Docs", owner)
    sign_in(client, owner)
    old_page, recent_page = _trash(client, space, "Old"), _trash(client, space, "Recent")
    now = datetime.now(UTC)
    with ctx.sessions() as db:
        db.execute(
            update(Page)
            .where(Page.trash_root_id == uuid.UUID(old_page))
            .values(deleted_at=now - timedelta(days=31))
        )
        db.execute(
            update(Page)
            .where(Page.trash_root_id == uuid.UUID(recent_page))
            .values(deleted_at=now - timedelta(days=29))
        )
        db.add_all(
            [
                BlockedIp(
                    ip="198.51.100.1",
                    reason="t",
                    hits=1,
                    blocked_at=now,
                    expires_at=now - timedelta(minutes=1),
                ),
                BlockedIp(
                    ip="198.51.100.2",
                    reason="t",
                    hits=1,
                    blocked_at=now,
                    expires_at=now + timedelta(hours=1),
                ),
                BlockedIp(ip="198.51.100.3", reason="t", hits=1, blocked_at=now, expires_at=None),
                ServerError(
                    occurred_at=now - timedelta(days=91),
                    source="request",
                    method="GET",
                    path="/",
                    status=500,
                ),
                ServerError(
                    occurred_at=now - timedelta(days=1),
                    source="request",
                    method="GET",
                    path="/",
                    status=500,
                ),
            ]
        )
        db.execute(update(IdempotencyKey).values(expires_at=now + timedelta(hours=1)))
        kept_keys = db.scalar(select(func.count()).select_from(IdempotencyKey))
        db.commit()

        counts = maintenance.purge_expired(db)

        assert counts["trashed_pages"] == 1
        assert counts["blocked_ips"] == 1
        assert counts["server_errors"] == 1
        assert counts["idempotency_keys"] == 0
        assert db.get(Page, uuid.UUID(old_page)) is None
        assert db.get(Page, uuid.UUID(recent_page)) is not None
        assert sorted(str(ip) for ip in db.scalars(select(BlockedIp.ip))) == [
            "198.51.100.2",
            "198.51.100.3",
        ]
        assert db.scalar(select(func.count()).select_from(ServerError)) == 1
        assert db.scalar(select(func.count()).select_from(IdempotencyKey)) == kept_keys
        assert db.scalar(select(func.count()).select_from(AuthSession)) == 1
