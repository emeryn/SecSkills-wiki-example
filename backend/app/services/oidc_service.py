"""OpenID Connect sign-in: authorization code flow with PKCE (S256).

* Discovery: the document's ``issuer`` must equal the configured issuer; every endpoint is https
  and fetched through the SSRF-checked, pinned HTTPS client.
* Flow state (``state``, ``nonce``, PKCE verifier) lives server-side, is single use, expires after
  10 minutes and is bound to the browser that started it by a ``SameSite=Lax`` cookie (the IdP
  redirect back is a cross-site top-level GET, which Lax allows).
* ID token: signature checked against the JWKS with the configured algorithm only (``none`` and
  ``HS*`` are impossible), then ``iss``, ``aud``, ``azp``, ``exp``/``iat``/``nbf`` and ``nonce``.
"""

import base64
import hashlib
import hmac
import json
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from urllib.parse import quote, urlencode

import jwt
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.core.outbound_http import OutboundHttpError, request
from app.core.outbound_url import Network, OutboundUrlError, resolve_url
from app.core.security import token_hash
from app.models import OidcFlow
from app.schemas.settings import OidcSettings

FLOW_LIFETIME = timedelta(minutes=10)
CACHE_SECONDS = 3600.0
CLOCK_SKEW_SECONDS = 60
REAUTH_MAX_AGE_SECONDS = 300
CALLBACK_PATH = "/api/v1/auth/oidc/callback"
BINDING_COOKIE = "__Host-oidc-flow"


class OidcError(Exception):
    """The flow failed; ``reason`` goes to the audit trail, the user sees a generic message."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class Provider:
    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str


class Transport:
    """HTTPS to the IdP through the outbound policy (tests substitute a fake IdP)."""

    def __init__(self, allowed: list[Network], ca_pem: str | None) -> None:
        self._allowed = allowed
        self._ca_pem = ca_pem

    def _call(self, url: str, method: str, body: bytes | None, headers: dict[str, str]) -> bytes:
        try:
            destination = resolve_url(url, self._allowed)
            response = request(destination, method, body=body, headers=headers, ca_pem=self._ca_pem)
        except (OutboundUrlError, OutboundHttpError) as exc:
            raise OidcError("idp_unreachable") from exc
        if response.status != 200:  # noqa: PLR2004
            raise OidcError(f"idp_status_{response.status}")
        return response.body

    def get_json(self, url: str) -> dict[str, Any]:
        return _json(self._call(url, "GET", None, {"Accept": "application/json"}))

    def post_form(self, url: str, form: dict[str, str], headers: dict[str, str]) -> dict[str, Any]:
        body = urlencode(form).encode()
        all_headers = {
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
            **headers,
        }
        return _json(self._call(url, "POST", body, all_headers))


TransportFactory = Callable[[OidcSettings, list[Network]], Transport]


def make_transport(config: OidcSettings, allowed: list[Network]) -> Transport:
    return Transport(allowed, config.ca_pem)


def _json(data: bytes) -> dict[str, Any]:
    try:
        value = json.loads(data)
    except ValueError as exc:
        raise OidcError("invalid_json") from exc
    if not isinstance(value, dict):
        raise OidcError("invalid_json")
    return cast(dict[str, Any], value)


_cache_lock = threading.Lock()
_discovery: dict[str, tuple[float, Provider]] = {}
_jwks: dict[str, tuple[float, dict[str, Any]]] = {}


def clear_cache() -> None:
    with _cache_lock:
        _discovery.clear()
        _jwks.clear()


def discover(config: OidcSettings, transport: Transport) -> Provider:
    issuer = config.issuer or ""
    with _cache_lock:
        cached = _discovery.get(issuer)
    if cached is not None and time.monotonic() - cached[0] < CACHE_SECONDS:
        return cached[1]
    document = transport.get_json(issuer.rstrip("/") + "/.well-known/openid-configuration")
    if document.get("issuer") != issuer:
        raise OidcError("issuer_mismatch")
    endpoints = {}
    for name in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
        value = document.get(name)
        if not isinstance(value, str) or not value.startswith("https://"):
            raise OidcError(f"invalid_{name}")
        endpoints[name] = value
    provider = Provider(issuer=issuer, **endpoints)
    with _cache_lock:
        _discovery[issuer] = (time.monotonic(), provider)
    return provider


def _signing_key(provider: Provider, transport: Transport, kid: str | None, refresh: bool) -> Any:
    with _cache_lock:
        cached = _jwks.get(provider.jwks_uri)
    if refresh or cached is None or time.monotonic() - cached[0] >= CACHE_SECONDS:
        cached = (time.monotonic(), transport.get_json(provider.jwks_uri))
        with _cache_lock:
            _jwks[provider.jwks_uri] = cached
    try:
        keys = jwt.PyJWKSet.from_dict(cached[1]).keys
    except jwt.PyJWTError as exc:
        raise OidcError("invalid_jwks") from exc
    candidates = [
        key
        for key in keys
        if (kid is None or key.key_id == kid) and key.public_key_use in (None, "sig")
    ]
    return candidates[0] if len(candidates) == 1 or (kid and candidates) else None


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def safe_next(path: str | None) -> str:
    """Only same-origin paths (open redirect protection)."""
    if not path or not path.startswith("/") or path.startswith("//") or "\\" in path:
        return "/"
    return path[:500]


def start(
    db: Session,
    config: OidcSettings,
    transport: Transport,
    public_origin: str,
    next_path: str | None,
    *,
    session_id: Any = None,
) -> tuple[str, str]:
    """Record a flow; returns ``(authorization URL, browser binding token)``."""
    provider = discover(config, transport)
    now = datetime.now(UTC)
    db.execute(delete(OidcFlow).where(OidcFlow.expires_at < now))
    state, nonce = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    verifier, binding = secrets.token_urlsafe(64), secrets.token_urlsafe(32)
    reauth = session_id is not None
    db.add(
        OidcFlow(
            state_hash=token_hash(state),
            binding_hash=token_hash(binding),
            nonce=nonce,
            code_verifier=verifier,
            purpose="reauth" if reauth else "login",
            next_path=safe_next(next_path),
            session_id=session_id,
            expires_at=now + FLOW_LIFETIME,
        )
    )
    params = {
        "response_type": "code",
        "client_id": config.client_id or "",
        "redirect_uri": public_origin + CALLBACK_PATH,
        "scope": " ".join(config.scopes),
        "state": state,
        "nonce": nonce,
        "code_challenge": _b64url(hashlib.sha256(verifier.encode()).digest()),
        "code_challenge_method": "S256",
    }
    if reauth:
        params.update({"prompt": "login", "max_age": "0"})
    separator = "&" if "?" in provider.authorization_endpoint else "?"
    return provider.authorization_endpoint + separator + urlencode(params), binding


def take_flow(db: Session, state: str | None, binding: str | None) -> OidcFlow:
    """The pending flow for ``state``, deleted (single use); the browser must match."""
    if not state or len(state) > 200:  # noqa: PLR2004
        raise OidcError("state_missing")
    flow = db.get(OidcFlow, token_hash(state))
    if flow is None:
        raise OidcError("state_unknown")
    db.delete(flow)
    db.flush()
    if flow.expires_at < datetime.now(UTC):
        raise OidcError("state_expired")
    if not binding or not hmac.compare_digest(flow.binding_hash, token_hash(binding)):
        raise OidcError("browser_mismatch")
    return flow


def discard_flow(db: Session, state: str) -> None:
    db.execute(delete(OidcFlow).where(OidcFlow.state_hash == token_hash(state)))


def _client_auth(config: OidcSettings) -> dict[str, str]:
    # client_secret_basic (RFC 6749 2.3.1): both parts form-encoded before base64.
    credentials = (
        f"{quote(config.client_id or '', safe='')}:{quote(config.client_secret or '', safe='')}"
    )
    return {"Authorization": "Basic " + base64.b64encode(credentials.encode()).decode()}


def validate_id_token(
    token: str,
    config: OidcSettings,
    provider: Provider,
    transport: Transport,
    nonce: str,
) -> dict[str, Any]:
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as exc:
        raise OidcError("id_token_malformed") from exc
    if header.get("alg") != config.id_token_algorithm:
        raise OidcError("id_token_algorithm")
    kid = header.get("kid")
    key = _signing_key(provider, transport, kid, refresh=False) or _signing_key(
        provider, transport, kid, refresh=True
    )
    if key is None:
        raise OidcError("id_token_unknown_key")
    try:
        claims: dict[str, Any] = jwt.decode(
            token,
            key=key.key,
            algorithms=[config.id_token_algorithm],
            audience=config.client_id,
            issuer=provider.issuer,
            leeway=CLOCK_SKEW_SECONDS,
            options={"require": ["exp", "iat", "iss", "aud", "sub"]},
        )
    except jwt.PyJWTError as exc:
        raise OidcError("id_token_invalid") from exc
    audiences = claims["aud"] if isinstance(claims["aud"], list) else [claims["aud"]]
    if len(audiences) > 1 and claims.get("azp") != config.client_id:
        raise OidcError("id_token_azp")
    if not isinstance(claims.get("nonce"), str) or not hmac.compare_digest(claims["nonce"], nonce):
        raise OidcError("nonce_mismatch")
    if not isinstance(claims["sub"], str) or not 1 <= len(claims["sub"]) <= 255:  # noqa: PLR2004
        raise OidcError("id_token_sub")
    return claims


def exchange(
    config: OidcSettings, transport: Transport, flow: OidcFlow, code: str, public_origin: str
) -> dict[str, Any]:
    """Code → validated ID token claims."""
    if not code or len(code) > 2048:  # noqa: PLR2004
        raise OidcError("code_missing")
    provider = discover(config, transport)
    tokens = transport.post_form(
        provider.token_endpoint,
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": public_origin + CALLBACK_PATH,
            "code_verifier": flow.code_verifier,
        },
        _client_auth(config),
    )
    id_token = tokens.get("id_token")
    if not isinstance(id_token, str):
        raise OidcError("id_token_missing")
    claims = validate_id_token(id_token, config, provider, transport, flow.nonce)
    if flow.purpose == "reauth":
        auth_time = claims.get("auth_time")
        if not isinstance(auth_time, int) or time.time() - auth_time > REAUTH_MAX_AGE_SECONDS:
            raise OidcError("reauth_not_fresh")
    return claims


def check(config: OidcSettings, transport: Transport) -> str:
    """Discovery and key download, for "Test connection"."""
    clear_cache()
    provider = discover(config, transport)
    keys = transport.get_json(provider.jwks_uri).get("keys")
    count = len(keys) if isinstance(keys, list) else 0
    if count == 0:
        raise OidcError("no_signing_keys")
    return f"Discovery succeeded; {count} signing key(s) published"
