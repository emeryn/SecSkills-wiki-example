from fastapi.testclient import TestClient

from app.core.context import AppContext
from app.services import bootstrap_admin
from tests.helpers import PASSWORD, make_user, sign_in, totp_code, write

BOOTSTRAP_PASSWORD = "generated-bootstrap-password-123"


def _bootstrap(ctx: AppContext) -> None:
    with ctx.sessions() as db:
        assert bootstrap_admin.ensure_bootstrap_admin(db, ctx, BOOTSTRAP_PASSWORD)
        assert not bootstrap_admin.ensure_bootstrap_admin(db, ctx, BOOTSTRAP_PASSWORD)


def test_bootstrap_admin_must_change_password_then_enroll(
    client: TestClient, ctx: AppContext
) -> None:
    _bootstrap(ctx)
    response = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": BOOTSTRAP_PASSWORD}
    )
    assert response.json()["state"] == "password_change_required"
    client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
    assert client.get("/api/v1/admin/users").status_code == 403

    new_password = "the operator chose this passphrase"
    response = client.post(
        "/api/v1/me/password",
        json={"current_password": BOOTSTRAP_PASSWORD, "new_password": new_password},
    )
    assert response.status_code == 200, response.text
    assert response.json()["state"] == "mfa_enrollment_required"
    client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
    assert client.get("/api/v1/admin/users").status_code == 403

    setup = client.post("/api/v1/me/mfa/totp")
    assert setup.status_code == 200, setup.text
    assert setup.json()["qr_png_data_uri"].startswith("data:image/png;base64,")
    secret = setup.json()["secret"]
    confirm = client.post("/api/v1/me/mfa/totp/confirm", json={"code": totp_code(secret)})
    assert confirm.status_code == 200, confirm.text
    assert confirm.json()["state"] == "active"
    assert len(confirm.json()["recovery_codes"]) == 10
    client.headers["X-CSRF-Token"] = confirm.json()["csrf_token"]
    assert client.get("/api/v1/admin/users").status_code == 200

    with ctx.sessions() as db:
        assert not bootstrap_admin.bootstrap_password_still_valid(db)


def test_recovery_code_signs_in_once(client: TestClient, ctx: AppContext) -> None:
    _bootstrap(ctx)
    login = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": BOOTSTRAP_PASSWORD}
    )
    client.headers["X-CSRF-Token"] = login.json()["csrf_token"]
    response = client.post(
        "/api/v1/me/password",
        json={"current_password": BOOTSTRAP_PASSWORD, "new_password": PASSWORD},
    )
    client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
    secret = client.post("/api/v1/me/mfa/totp").json()["secret"]
    codes = client.post("/api/v1/me/mfa/totp/confirm", json={"code": totp_code(secret)}).json()[
        "recovery_codes"
    ]

    for expected in (200, 401):
        with TestClient(
            client.app,
            base_url="https://testserver",
            headers={"X-Requested-With": "XMLHttpRequest"},
        ) as other:
            login = other.post(
                "/api/v1/auth/login", json={"username": "admin", "password": PASSWORD}
            )
            other.headers["X-CSRF-Token"] = login.json()["csrf_token"]
            response = other.post("/api/v1/auth/mfa/recovery", json={"code": codes[0]})
            assert response.status_code == expected


def test_session_info_and_logout(client: TestClient, ctx: AppContext) -> None:
    sign_in(client, make_user(ctx, "bob", email="bob@example.com"))
    info = client.get("/api/v1/auth/session").json()
    assert info["state"] == "active"
    assert info["user"]["email"] == "bob@example.com"
    assert info["user"]["permissions"] == []
    assert client.post("/api/v1/auth/logout").status_code == 204
    assert client.get("/api/v1/auth/session").status_code == 401


def test_list_and_revoke_own_sessions(client: TestClient, ctx: AppContext) -> None:
    bob = make_user(ctx, "bob")
    with TestClient(
        client.app, base_url="https://testserver", headers={"X-Requested-With": "XMLHttpRequest"}
    ) as other:
        sign_in(other, bob)
        sign_in(client, bob)
        sessions = client.get("/api/v1/me/sessions").json()
        assert len(sessions) == 2
        assert sum(s["current"] for s in sessions) == 1
        response = write(client, "POST", "/api/v1/me/sessions/revoke-others")
        assert response.json() == {"count": 1}
        assert other.get("/api/v1/auth/session").status_code == 401


def test_admin_cannot_remove_last_factor(client: TestClient, ctx: AppContext) -> None:
    sign_in(client, make_user(ctx, "root", role="admin"))
    response = write(client, "DELETE", "/api/v1/me/mfa/totp")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "LAST_FACTOR"
