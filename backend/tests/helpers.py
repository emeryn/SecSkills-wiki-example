"""Test helpers: users with known credentials, signed-in clients, TOTP codes."""

import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
import pyotp
from fastapi.testclient import TestClient

from app.core.context import AppContext
from app.models import TotpCredential, User
from app.services.mfa_service import TOTP_INTERVAL
from app.services.user_profile import new_user, set_profile

PASSWORD = "correct horse battery staple 42"


@dataclass
class TestUser:
    __test__ = False

    id: uuid.UUID
    username: str
    password: str
    totp_secret: str | None


def make_user(
    ctx: AppContext,
    username: str,
    *,
    role: str = "user",
    email: str | None = None,
    totp: bool | None = None,
    must_change_password: bool = False,
) -> TestUser:
    """Create a user directly in the database. Admins get TOTP unless ``totp=False``."""
    with_totp = role == "admin" if totp is None else totp
    secret = pyotp.random_base32(32) if with_totp else None
    with ctx.sessions() as db:
        user: User = new_user(ctx.cipher, username, role=role)
        set_profile(ctx.cipher, user, email=email, display_name=username.title())
        user.password_hash = ctx.hasher.hash(PASSWORD)
        user.must_change_password = must_change_password
        db.add(user)
        db.flush()
        if secret:
            dek = ctx.cipher.unwrap(user.dek_wrapped)
            db.add(
                TotpCredential(
                    user_id=user.id,
                    secret_enc=ctx.cipher.encrypt(
                        dek, secret, f"totp_credentials.secret:{user.id}"
                    ),
                    last_used_step=0,
                    confirmed_at=datetime.now(UTC),
                )
            )
        db.commit()
        return TestUser(user.id, username, PASSWORD, secret)


def totp_code(secret: str, steps_ahead: int = 0) -> str:
    return pyotp.TOTP(secret, interval=TOTP_INTERVAL).at(
        int(time.time()) + steps_ahead * TOTP_INTERVAL
    )


def write(client: TestClient, method: str, url: str, **kwargs: Any) -> httpx.Response:
    """State-changing call as the SPA does it: idempotency key and CSRF token headers."""
    headers = dict(kwargs.pop("headers", {}) or {})
    headers.setdefault("Idempotency-Key", str(uuid.uuid4()))
    response: httpx.Response = client.request(method, url, headers=headers, **kwargs)
    return response


def sign_in(client: TestClient, user: TestUser, *, steps_ahead: int = 0) -> httpx.Response:
    """Password (+ TOTP when enrolled); stores the CSRF token on the client."""
    response = client.post(
        "/api/v1/auth/login", json={"username": user.username, "password": user.password}
    )
    assert response.status_code == 200, response.text
    client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
    if response.json()["state"] == "mfa_required" and user.totp_secret:
        response = client.post(
            "/api/v1/auth/mfa/totp", json={"code": totp_code(user.totp_secret, steps_ahead)}
        )
        assert response.status_code == 200, response.text
        client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
    result: httpx.Response = response
    return result


def make_space(
    ctx: AppContext,
    name: str,
    space_admin: TestUser,
    *,
    visibility: str = "restricted",
    members: dict[str, tuple[TestUser, str]] | None = None,
) -> str:
    """Create a space (with its home page) and memberships; returns the space key."""
    from app.models import SpaceMember  # noqa: PLC0415 - keeps the helper imports light
    from app.services import space_service  # noqa: PLC0415
    from app.services.audit_service import Actor  # noqa: PLC0415

    actor = Actor(user_id=space_admin.id, ip=None, user_agent="tests", request_id=None)
    with ctx.sessions() as db:
        space = space_service.create_space(
            db,
            name=name,
            description="",
            visibility=visibility,
            space_admin_id=space_admin.id,
            actor=actor,
        )
        for user, role in (members or {}).values():
            db.add(
                SpaceMember(
                    space_id=space.id, principal_type="user", principal_id=user.id, role=role
                )
            )
        db.commit()
        return space.key
