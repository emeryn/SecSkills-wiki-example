"""Test doubles for single sign-on: a fake OpenID provider and an in-memory directory."""

import base64
import hashlib
import secrets
import time
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlsplit

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from ldap3 import MOCK_SYNC, Connection, Server

from app.core.context import AppContext
from app.core.outbound_url import Network
from app.core.runtime_settings import encrypt_section
from app.models import Setting
from app.schemas.settings import SECTION_MODELS, LdapSettings
from app.services.ldap_service import DirectoryUnavailableError
from app.services.oidc_service import OidcError, Transport

ISSUER = "https://idp.example.com"
CLIENT_ID = "wiki"
CLIENT_SECRET = "oidc-client-secret-0123456789abcdef-tail"


def configure(ctx: AppContext, section: str, **values: Any) -> None:
    """Save a settings section as the administration API would (validated, encrypted)."""
    model = SECTION_MODELS[section].model_validate(values)
    with ctx.sessions() as db:
        row = db.get(Setting, section) or Setting(key=section)
        encrypt_section(ctx.cipher, row, model.model_dump())
        row.updated_at = datetime.now(UTC)
        db.add(row)
        db.commit()
    ctx.runtime.refresh()


def oidc_values(**overrides: Any) -> dict[str, Any]:
    return {
        "enabled": True,
        "issuer": ISSUER,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        **overrides,
    }


class FakeIdP(Transport):
    """Discovery, JWKS and a token endpoint that checks PKCE, signing with a real RSA key."""

    def __init__(self) -> None:
        super().__init__([], None)
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.kid = "key-1"
        self.pending: dict[str, dict[str, Any]] = {}
        self.token_requests: list[dict[str, str]] = []

    def get_json(self, url: str) -> dict[str, Any]:
        # Whatever issuer is configured, this provider announces its own.
        if url.endswith("/.well-known/openid-configuration"):
            return {
                "issuer": ISSUER,
                "authorization_endpoint": ISSUER + "/authorize",
                "token_endpoint": ISSUER + "/token",
                "jwks_uri": ISSUER + "/jwks",
            }
        if url == ISSUER + "/jwks":
            jwk = jwt.algorithms.RSAAlgorithm.to_jwk(self.key.public_key(), as_dict=True)
            return {"keys": [{**jwk, "kid": self.kid, "use": "sig", "alg": "RS256"}]}
        raise OidcError("idp_status_404")

    def post_form(self, url: str, form: dict[str, str], headers: dict[str, str]) -> dict[str, Any]:
        self.token_requests.append(form)
        pending = self.pending.pop(form.get("code", ""), None)
        if pending is None:
            raise OidcError("idp_status_400")
        digest = hashlib.sha256(form["code_verifier"].encode()).digest()
        if base64.urlsafe_b64encode(digest).rstrip(b"=").decode() != pending["challenge"]:
            raise OidcError("idp_status_400")
        claims = {"nonce": pending["nonce"], **pending["claims"]}
        return {"id_token": pending["token"] or self.id_token(**claims)}

    def authorize(self, location: str, token: str | None = None, **claims: Any) -> dict[str, str]:
        """What the IdP does after the user signs in: returns the callback query parameters."""
        params = {k: v[0] for k, v in parse_qs(urlsplit(location).query).items()}
        code = secrets.token_urlsafe(16)
        self.pending[code] = {
            "nonce": params["nonce"],
            "challenge": params["code_challenge"],
            "claims": claims,
            "token": token,
        }
        return {"state": params["state"], "code": code}

    def claims(self, *, nonce: str, **overrides: Any) -> dict[str, Any]:
        now = int(time.time())
        payload: dict[str, Any] = {
            "iss": ISSUER,
            "sub": "subject-alice",
            "aud": CLIENT_ID,
            "iat": now,
            "exp": now + 300,
            "auth_time": now,
            "nonce": nonce,
            "preferred_username": "alice",
            "email": "alice@example.com",
            "name": "Alice Example",
            "groups": [],
        }
        payload.update(overrides)
        return payload

    def id_token(self, *, nonce: str, **claims: Any) -> str:
        payload = self.claims(nonce=nonce, **claims)
        return jwt.encode(payload, self.key, algorithm="RS256", headers={"kid": self.kid})


def ldap_values(**overrides: Any) -> dict[str, Any]:
    return {
        "enabled": True,
        "url": "ldaps://ldap.example.com",
        "bind_dn": "cn=svc,dc=example,dc=com",
        "bind_password": "service-password",
        "user_base_dn": "ou=people,dc=example,dc=com",
        "group_base_dn": "ou=groups,dc=example,dc=com",
        **overrides,
    }


class FakeDirectory:
    """ldap3 mock server shared by every connection; passwords are checked on bind."""

    def __init__(self) -> None:
        self.server = Server("fake-directory")
        self.binds: list[str | None] = []
        self.available = True
        seed = Connection(self.server, client_strategy=MOCK_SYNC)
        seed.strategy.add_entry(
            "cn=svc,dc=example,dc=com",
            {"objectClass": "person", "userPassword": "service-password"},
        )

    def add_user(
        self, uid: str, password: str, groups: list[str] | None = None, **attributes: str
    ) -> str:
        dn = f"uid={uid},ou=people,dc=example,dc=com"
        seed = Connection(self.server, client_strategy=MOCK_SYNC)
        seed.strategy.add_entry(
            dn,
            {
                "objectClass": "person",
                "uid": uid,
                "userPassword": password,
                "mail": f"{uid}@example.com",
                "cn": uid.title(),
                "entryUUID": f"uuid-{uid}",
                **attributes,
            },
        )
        for group in groups or []:
            seed.strategy.add_entry(
                f"cn={group},ou=groups,dc=example,dc=com",
                {"objectClass": "groupOfNames", "cn": group, "member": [dn]},
            )
        return dn

    def connect(
        self, config: LdapSettings, allowed: list[Network], user: str | None, password: str | None
    ) -> Connection:
        if not self.available:
            raise OSError("unreachable")
        self.binds.append(user)
        connection = Connection(
            self.server, user=user, password=password, client_strategy=MOCK_SYNC
        )
        if not connection.bind():
            raise DirectoryUnavailableError("Bind refused")
        return connection
