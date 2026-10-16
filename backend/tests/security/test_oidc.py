"""OIDC sign-in: PKCE, state/nonce, browser binding, ID token checks, provisioning, step-up."""

import base64
import json
from collections.abc import Iterator
from typing import Any

import httpx
import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.context import AppContext
from app.models import AuditEvent, SpaceMember, User
from app.services import oidc_service
from tests.helpers import make_space, make_user, sign_in, write
from tests.sso_helpers import CLIENT_SECRET, FakeIdP, configure, oidc_values


@pytest.fixture
def idp(ctx: AppContext, monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeIdP]:
    fake = FakeIdP()
    oidc_service.clear_cache()
    monkeypatch.setattr(oidc_service, "make_transport", lambda config, allowed: fake)
    configure(ctx, "oidc", **oidc_values())
    yield fake
    oidc_service.clear_cache()


def _start(client: TestClient, next_path: str = "/spaces") -> httpx.Response:
    response: httpx.Response = client.get(
        "/api/v1/auth/oidc/start", params={"next": next_path}, follow_redirects=False
    )
    assert response.status_code == 303, response.text
    return response


def _callback(client: TestClient, params: dict[str, str]) -> httpx.Response:
    # The IdP redirect is a cross-site top-level navigation.
    response: httpx.Response = client.get(
        "/api/v1/auth/oidc/callback",
        params=params,
        headers={"Sec-Fetch-Site": "cross-site"},
        follow_redirects=False,
    )
    return response


def _sign_in(client: TestClient, idp: FakeIdP, **claims: Any) -> httpx.Response:
    start = _start(client)
    return _callback(client, idp.authorize(start.headers["location"], **claims))


def _failure_reasons(ctx: AppContext) -> list[str]:
    with ctx.sessions() as db:
        events = db.scalars(
            select(AuditEvent).where(
                AuditEvent.action == "auth.login", AuditEvent.outcome == "failure"
            )
        ).all()
    return [str((e.after or {}).get("reason")) for e in events]


def test_authorization_request_uses_pkce_and_state(client: TestClient, idp: FakeIdP) -> None:
    location = _start(client).headers["location"]
    assert location.startswith("https://idp.example.com/authorize?")
    query = httpx.URL(location).params
    assert query["response_type"] == "code"
    assert query["code_challenge_method"] == "S256"
    assert query["redirect_uri"] == "https://testserver/api/v1/auth/oidc/callback"
    assert len(query["state"]) >= 40 and len(query["nonce"]) >= 40
    assert "openid" in query["scope"].split()


def test_sign_in_with_samesite_lax_cookies_provisions_and_maps_groups(
    client: TestClient, ctx: AppContext, idp: FakeIdP
) -> None:
    owner = make_user(ctx, "owner")
    space = make_space(ctx, "Engineering", owner)
    configure(
        ctx,
        "oidc",
        **oidc_values(group_mapping=[{"group": "Eng", "space": space, "role": "editor"}]),
    )
    start = _start(client)
    binding_cookie = start.headers["set-cookie"].lower()
    assert "__host-oidc-flow=" in binding_cookie
    assert "samesite=lax" in binding_cookie and "secure" in binding_cookie
    assert "httponly" in binding_cookie

    callback = _callback(client, idp.authorize(start.headers["location"], groups=["eng"]))
    assert callback.status_code == 303
    assert callback.headers["location"] == "/spaces"
    session_cookie = next(
        c for c in callback.headers.get_list("set-cookie") if c.startswith("__Host-session=")
    )
    assert "samesite=lax" in session_cookie.lower()

    info = client.get("/api/v1/auth/session").json()
    assert info["user"]["username"] == "alice"
    assert info["user"]["auth_source"] == "oidc"
    assert idp.token_requests[0]["grant_type"] == "authorization_code"
    with ctx.sessions() as db:
        user = db.scalar(select(User).where(User.username == "alice"))
        assert user is not None and user.password_hash is None
        member = db.scalar(select(SpaceMember).where(SpaceMember.principal_id == user.id))
    assert member is not None and (member.role, member.source) == ("editor", "sso")


def test_group_sync_never_touches_manual_memberships(
    client: TestClient, ctx: AppContext, idp: FakeIdP
) -> None:
    owner = make_user(ctx, "owner")
    space = make_space(ctx, "Engineering", owner)
    configure(
        ctx,
        "oidc",
        **oidc_values(group_mapping=[{"group": "eng", "space": space, "role": "viewer"}]),
    )
    _sign_in(client, idp, groups=["eng"])
    with ctx.sessions() as db:
        alice = db.scalar(select(User).where(User.username == "alice"))
        assert alice is not None
        row = db.scalar(select(SpaceMember).where(SpaceMember.principal_id == alice.id))
        assert row is not None
        row.source, row.role = "manual", "space_admin"
        db.commit()
    client.cookies.clear()
    _sign_in(client, idp, groups=[])
    with ctx.sessions() as db:
        rows = db.scalars(select(SpaceMember).where(SpaceMember.principal_id == alice.id)).all()
    assert [(r.role, r.source) for r in rows] == [("space_admin", "manual")]


def test_group_removal_revokes_sso_membership(
    client: TestClient, ctx: AppContext, idp: FakeIdP
) -> None:
    owner = make_user(ctx, "owner")
    space = make_space(ctx, "Engineering", owner)
    configure(
        ctx,
        "oidc",
        **oidc_values(group_mapping=[{"group": "eng", "space": space, "role": "editor"}]),
    )
    _sign_in(client, idp, groups=["eng"])
    client.cookies.clear()
    _sign_in(client, idp, groups=["sales"])
    with ctx.sessions() as db:
        members = db.scalars(select(SpaceMember).where(SpaceMember.source == "sso")).all()
        synced = db.scalars(
            select(AuditEvent.action).where(AuditEvent.action == "space.member_synced")
        ).all()
    assert members == []
    assert len(synced) == 2


@pytest.mark.parametrize(
    ("tamper", "reason"),
    [
        ("unknown_state", "state_unknown"),
        ("other_browser", "browser_mismatch"),
        ("replay", "state_unknown"),
        ("idp_error", "idp_error"),
        ("issuer_param", "issuer_mismatch"),
    ],
)
def test_callback_tampering_is_refused(
    client: TestClient, ctx: AppContext, idp: FakeIdP, tamper: str, reason: str
) -> None:
    start = _start(client)
    params = idp.authorize(start.headers["location"])
    if tamper == "unknown_state":
        params["state"] = "x" * 43
    elif tamper == "other_browser":
        client.cookies.delete("__Host-oidc-flow")
    elif tamper == "replay":
        assert _callback(client, params).headers["location"] == "/spaces"
        client.cookies.clear()
        start = _start(client)
    elif tamper == "idp_error":
        params["error"] = "access_denied"
    elif tamper == "issuer_param":
        params["iss"] = "https://evil.example.com"
    response = _callback(client, params)
    assert response.status_code == 303
    assert response.headers["location"] == "/login?error=sso"
    assert reason in _failure_reasons(ctx)


@pytest.mark.parametrize(
    ("claims", "reason"),
    [
        ({"nonce": "attacker-nonce"}, "nonce_mismatch"),
        ({"aud": "another-client"}, "id_token_invalid"),
        ({"iss": "https://evil.example.com"}, "id_token_invalid"),
        ({"exp": 1_000_000_000}, "id_token_invalid"),
        ({"aud": ["wiki", "other"]}, "id_token_azp"),
    ],
)
def test_invalid_id_tokens_are_refused(
    client: TestClient, ctx: AppContext, idp: FakeIdP, claims: dict[str, Any], reason: str
) -> None:
    response = _sign_in(client, idp, **claims)
    assert response.headers["location"] == "/login?error=sso"
    assert reason in _failure_reasons(ctx)
    assert client.get("/api/v1/auth/session").status_code == 401


def _segment(value: dict[str, Any]) -> str:
    return base64.urlsafe_b64encode(json.dumps(value).encode()).rstrip(b"=").decode()


@pytest.mark.parametrize("algorithm", ["none", "HS256"])
def test_unsigned_and_symmetric_tokens_are_refused(
    client: TestClient, ctx: AppContext, idp: FakeIdP, algorithm: str
) -> None:
    location = _start(client).headers["location"]
    payload = idp.claims(nonce=httpx.URL(location).params["nonce"])
    if algorithm == "none":
        token = _segment({"alg": "none", "typ": "JWT"}) + "." + _segment(payload) + "."
    else:
        # A token "signed" with the client secret, as in the HS256 key-confusion attack.
        token = jwt.encode(payload, CLIENT_SECRET, algorithm="HS256")
    response = _callback(client, idp.authorize(location, token=token))
    assert response.headers["location"] == "/login?error=sso"
    assert "id_token_algorithm" in _failure_reasons(ctx)


def test_no_takeover_of_a_local_account_with_the_same_name(
    client: TestClient, ctx: AppContext, idp: FakeIdP
) -> None:
    make_user(ctx, "alice")
    response = _sign_in(client, idp)
    assert response.headers["location"] == "/login?error=sso"
    assert "username_taken" in _failure_reasons(ctx)


def test_open_redirect_in_next_is_neutralized(client: TestClient, idp: FakeIdP) -> None:
    start = _start(client, next_path="//evil.example.com/x")
    response = _callback(client, idp.authorize(start.headers["location"]))
    assert response.headers["location"] == "/"


def test_role_of_sso_accounts_is_managed_by_groups(
    client: TestClient, ctx: AppContext, idp: FakeIdP
) -> None:
    _sign_in(client, idp)
    with ctx.sessions() as db:
        alice_id = db.scalar(select(User.id).where(User.username == "alice"))
    with TestClient(
        client.app, base_url="https://testserver", headers={"X-Requested-With": "XMLHttpRequest"}
    ) as admin:
        sign_in(admin, make_user(ctx, "root", role="admin"))
        response = write(admin, "PATCH", f"/api/v1/admin/users/{alice_id}", json={"role": "admin"})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ROLE_MANAGED_BY_SSO"


def test_admin_group_grants_admin_with_mandatory_mfa(
    client: TestClient, ctx: AppContext, idp: FakeIdP
) -> None:
    make_user(ctx, "root", role="admin")
    configure(ctx, "oidc", **oidc_values(admin_groups=["Wiki-Admins"]))
    response = _sign_in(client, idp, groups=["wiki-admins"])
    # Admin rights only after a second factor: none enrolled yet, so enrollment comes first.
    assert response.headers["location"] == "/setup/security?next=/spaces"
    info = client.get("/api/v1/auth/session").json()
    assert info["state"] == "mfa_enrollment_required"
    assert info["user"]["role"] == "admin"
    assert "users:read" not in info["user"]["permissions"]
    with ctx.sessions() as db:
        synced = db.scalar(select(AuditEvent).where(AuditEvent.action == "user.role_synced"))
    assert synced is not None and synced.after == {"role": "admin", "source": "oidc"}

    client.cookies.clear()
    _sign_in(client, idp, groups=[])
    assert client.get("/api/v1/auth/session").json()["user"]["role"] == "user"


def test_last_administrator_is_never_demoted_by_groups(
    client: TestClient, ctx: AppContext, idp: FakeIdP
) -> None:
    configure(ctx, "oidc", **oidc_values(admin_groups=["wiki-admins"]))
    _sign_in(client, idp, groups=["wiki-admins"])
    client.cookies.clear()
    _sign_in(client, idp, groups=[])
    with ctx.sessions() as db:
        role = db.scalar(select(User.global_role).where(User.username == "alice"))
    assert role == "admin"


def test_step_up_goes_through_the_identity_provider(
    client: TestClient, ctx: AppContext, idp: FakeIdP
) -> None:
    _sign_in(client, idp)
    client.headers["X-CSRF-Token"] = client.get("/api/v1/auth/session").json()["csrf_token"]
    refused = write(client, "POST", "/api/v1/auth/reauth", json={"password": "anything"})
    assert refused.json()["error"]["code"] == "REAUTH_WITH_SSO"

    start = client.get(
        "/api/v1/auth/oidc/reauth", params={"next": "/account"}, follow_redirects=False
    )
    query = httpx.URL(start.headers["location"]).params
    assert (query["prompt"], query["max_age"]) == ("login", "0")
    stale = _callback(client, idp.authorize(start.headers["location"], auth_time=1_000_000_000))
    assert stale.headers["location"] == "/login?error=sso"
    assert "reauth_not_fresh" in _failure_reasons(ctx)

    start = client.get(
        "/api/v1/auth/oidc/reauth", params={"next": "/account"}, follow_redirects=False
    )
    fresh = _callback(client, idp.authorize(start.headers["location"]))
    assert fresh.headers["location"] == "/account"
    with ctx.sessions() as db:
        assert db.scalar(select(AuditEvent).where(AuditEvent.action == "auth.reauth")) is not None


def test_disabled_provider_answers_not_found(client: TestClient, ctx: AppContext) -> None:
    assert client.get("/api/v1/auth/oidc/start", follow_redirects=False).status_code == 404
    assert client.get("/api/v1/auth/methods").json() == {
        "oidc": False,
        "oidc_label": "Single sign-on",
        "directory": False,
    }
