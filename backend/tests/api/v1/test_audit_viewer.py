"""Audit viewer: filters, CSV formula-injection escaping, audited and re-authenticated export."""

import csv
import io

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from app.core.context import AppContext
from app.models import AuditEvent, AuthSession
from app.services import audit_service
from app.services.audit_export import escape_cell
from app.services.audit_service import SYSTEM, Actor
from tests.helpers import make_user, sign_in

PAYLOAD = "=CMD|' /C calc'!A0"


@pytest.fixture
def admin(client: TestClient, ctx: AppContext) -> TestClient:
    sign_in(client, make_user(ctx, "root", role="admin"))
    return client


def _record(
    ctx: AppContext,
    action: str,
    *,
    actor: Actor = SYSTEM,
    outcome: str = "success",
    severity: str = "info",
    target_type: str | None = None,
    target_id: str | None = None,
) -> None:
    with ctx.sessions() as db:
        audit_service.record(
            db,
            actor,
            action,
            outcome=outcome,
            severity=severity,
            target_type=target_type,
            target_id=target_id,
        )
        db.commit()


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("=CMD()", "'=CMD()"),
        ("+1+1", "'+1+1"),
        ("-2", "'-2"),
        ("@SUM(A1)", "'@SUM(A1)"),
        ("\t=1", "'\t=1"),
        ("\r=1", "'\r=1"),
        ("plain", "plain"),
        (None, ""),
        ({"note": "=1"}, '{"note": "=1"}'),
    ],
)
def test_escape_cell(value: object, expected: str) -> None:
    assert escape_cell(value) == expected


def test_csv_export_neutralizes_formulas_and_is_audited(admin: TestClient, ctx: AppContext) -> None:
    _record(
        ctx,
        "space.renamed",
        actor=Actor(user_id=None, ip="198.51.100.1", user_agent=PAYLOAD, request_id=None),
        target_type="space",
        target_id="=HYPERLINK(1)",
    )
    response = admin.get("/api/v1/admin/audit/export", params={"action": "space.renamed"})
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/csv")
    assert response.headers["content-disposition"].startswith('attachment; filename="audit-')
    rows = list(csv.reader(io.StringIO(response.content.decode("utf-8-sig"))))
    header, [row] = rows[0], rows[1:]
    record = dict(zip(header, row, strict=True))
    assert record["user_agent"] == "'" + PAYLOAD
    assert record["target_id"] == "'=HYPERLINK(1)"
    assert all(not cell.startswith(("=", "+", "-", "@")) for cell in row)

    with ctx.sessions() as db:
        exported = db.scalar(select(AuditEvent).where(AuditEvent.action == "audit.exported"))
    assert exported is not None
    assert exported.after == {"filters": {"action": "space.renamed"}, "rows": 1}


def test_export_needs_recent_authentication(admin: TestClient, ctx: AppContext) -> None:
    with ctx.sessions() as db:
        db.execute(update(AuthSession).values(reauth_at=None))
        db.commit()
    response = admin.get("/api/v1/admin/audit/export")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "REAUTH_REQUIRED"


def test_filters(admin: TestClient, ctx: AppContext) -> None:
    _record(ctx, "auth.login", outcome="failure")
    _record(ctx, "auth.logout")
    _record(ctx, "security.honeytoken", severity="critical", outcome="failure")

    def actions(**params: str) -> list[str]:
        response = admin.get("/api/v1/admin/audit", params=params)
        assert response.status_code == 200, response.text
        return [item["action"] for item in response.json()["items"]]

    assert actions(action="auth.login", outcome="failure") == ["auth.login"]
    prefixed = set(actions(action="auth."))
    assert {"auth.login", "auth.logout"} <= prefixed
    assert all(action.startswith("auth.") for action in prefixed)
    assert actions(severity="critical") == ["security.honeytoken"]
    assert "auth.logout" in actions(actor="system")
    assert "auth.login" in actions(actor="root")
    assert actions(actor="nobody") == []
    assert "security.honeytoken" in admin.get("/api/v1/admin/audit/actions").json()


@pytest.mark.parametrize(
    "params",
    [{"page_size": "101"}, {"ip": "not-an-ip"}, {"action": "DROP TABLE"}, {"sort": "id"}],
)
def test_invalid_filters_are_rejected(admin: TestClient, params: dict[str, str]) -> None:
    assert admin.get("/api/v1/admin/audit", params=params).status_code == 422
