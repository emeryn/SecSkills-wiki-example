"""Single sign-on endpoints: available methods, OIDC start, callback and step-up.

These are browser navigations (not XHR): they answer with redirects. The callback is reached by a
cross-site top-level GET from the identity provider, which ``SameSite=Lax`` cookies accompany.
"""

from typing import Annotated, Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from app.api.deps import (
    Ctx,
    CurrentActor,
    CurrentPrincipal,
    Db,
    authenticated,
    public,
    set_session_cookie,
)
from app.core.context import AppContext
from app.core.csrf import SESSION_COOKIE
from app.core.errors import AppError
from app.services import audit_service, auth_service, oidc_service, session_service, sso_config
from app.services.audit_service import Actor
from app.services.oidc_service import BINDING_COOKIE, OidcError
from app.services.sso_provisioning import Identity, SsoError, sign_in_user

router = APIRouter(prefix="/auth", tags=["auth"])

NextPath = Annotated[str | None, Query(alias="next", max_length=500)]


class AuthMethods(BaseModel):
    oidc: bool
    oidc_label: str
    directory: bool


@router.get("/methods", dependencies=[Depends(public)])
def methods(ctx: Ctx) -> AuthMethods:
    oidc = sso_config.oidc(ctx)
    return AuthMethods(
        oidc=oidc.enabled, oidc_label=oidc.display_name, directory=sso_config.ldap(ctx).enabled
    )


def _redirect(location: str) -> RedirectResponse:
    return RedirectResponse(location, status_code=303)


def _start(
    db: Db, ctx: AppContext, next_path: str | None, session_id: Any = None
) -> RedirectResponse:
    config = sso_config.oidc(ctx)
    if not config.enabled:
        raise AppError(404, "NOT_FOUND", "Not found")
    transport = oidc_service.make_transport(config, sso_config.allowed_networks(ctx, "oidc"))
    try:
        url, binding = oidc_service.start(
            db, config, transport, ctx.settings.public_origin, next_path, session_id=session_id
        )
    except OidcError as exc:
        audit_service.record(
            db,
            audit_service.SYSTEM,
            "auth.sso_unavailable",
            outcome="failure",
            after={"reason": exc.reason},
        )
        db.commit()
        return _redirect("/login?error=sso_unavailable")
    db.commit()
    response = _redirect(url)
    response.set_cookie(
        BINDING_COOKIE,
        binding,
        max_age=int(oidc_service.FLOW_LIFETIME.total_seconds()),
        path="/",
        secure=True,
        httponly=True,
        samesite="lax",
    )
    return response


@router.get("/oidc/start", dependencies=[Depends(public)])
def oidc_start(db: Db, ctx: Ctx, next_path: NextPath = None) -> RedirectResponse:
    return _start(db, ctx, next_path)


@router.get("/oidc/reauth", dependencies=[Depends(authenticated)])
def oidc_reauth(
    principal: CurrentPrincipal, db: Db, ctx: Ctx, next_path: NextPath = None
) -> RedirectResponse:
    """Step-up for OIDC accounts: the IdP is asked to authenticate the user again."""
    if principal.user.auth_source != "oidc":
        raise AppError(409, "NOT_SSO_ACCOUNT", "Confirm your identity with your password")
    return _start(db, ctx, next_path, session_id=principal.session.id)


def _identity(claims: dict[str, Any], ctx: AppContext) -> Identity:
    config = sso_config.oidc(ctx)

    def text(name: str) -> str | None:
        value = claims.get(name)
        return value if isinstance(value, str) else None

    groups = claims.get(config.groups_claim)
    email = text(config.email_claim)
    if claims.get("email_verified") is False:
        email = None
    return Identity(
        source="oidc",
        external_id=claims["sub"],
        username=text(config.username_claim) or "",
        email=email,
        display_name=text(config.name_claim),
        groups=[g for g in groups if isinstance(g, str)][:500] if isinstance(groups, list) else [],
    )


_STEP_PATHS = {
    "mfa_required": "/login/verify",
    "mfa_enrollment_required": "/setup/security",
}


def _finish_login(
    db: Db, ctx: AppContext, claims: dict[str, Any], actor: Actor, next_path: str
) -> RedirectResponse:
    config = sso_config.oidc(ctx)
    try:
        user = sign_in_user(
            db,
            ctx,
            _identity(claims, ctx),
            auto_provision=config.auto_provision,
            mapping=config.group_mapping,
            actor=actor,
            admin_groups=config.admin_groups,
        )
    except SsoError as exc:
        raise OidcError(exc.reason) from exc
    result = auth_service.sso_login(db, ctx, user, actor)
    target = next_path
    if result.session.state != "active":
        # Administrators still need their second factor (or must enroll one) after the IdP.
        step = _STEP_PATHS.get(result.session.state, "/login/verify")
        target = f"{step}?next={quote(next_path, safe='/')}"
    response = _redirect(target)
    set_session_cookie(response, result.token, result.session)
    return response


def _finish_reauth(
    request: Request,
    db: Db,
    ctx: AppContext,
    claims: dict[str, Any],
    actor: Actor,
    flow_session: Any,
    next_path: str,
) -> RedirectResponse:
    cookie = request.cookies.get(SESSION_COOKIE)
    principal = session_service.resolve(db, ctx, cookie) if cookie else None
    if (
        principal is None
        or principal.session.id != flow_session
        or principal.user.auth_source != "oidc"
        or principal.user.external_id != claims["sub"]
    ):
        raise OidcError("reauth_identity_mismatch")
    token = auth_service.sso_reauthenticated(db, ctx, principal, actor)
    response = _redirect(next_path)
    set_session_cookie(response, token, principal.session)
    return response


@router.get("/oidc/callback", dependencies=[Depends(public)])
def oidc_callback(
    request: Request,
    db: Db,
    ctx: Ctx,
    actor: CurrentActor,
    state: Annotated[str | None, Query(max_length=200)] = None,
    code: Annotated[str | None, Query(max_length=2048)] = None,
    error: Annotated[str | None, Query(max_length=200)] = None,
    iss: Annotated[str | None, Query(max_length=2000)] = None,
) -> RedirectResponse:
    config = sso_config.oidc(ctx)
    try:
        if not config.enabled:
            raise OidcError("disabled")
        flow = oidc_service.take_flow(db, state, request.cookies.get(BINDING_COOKIE))
        if error is not None:
            raise OidcError("idp_error")
        # RFC 9207: an authorization response from another issuer is a mix-up attack.
        if iss is not None and iss != config.issuer:
            raise OidcError("issuer_mismatch")
        transport = oidc_service.make_transport(config, sso_config.allowed_networks(ctx, "oidc"))
        claims = oidc_service.exchange(
            config, transport, flow, code or "", ctx.settings.public_origin
        )
        if flow.purpose == "reauth":
            response = _finish_reauth(
                request, db, ctx, claims, actor, flow.session_id, flow.next_path
            )
        else:
            response = _finish_login(db, ctx, claims, actor, flow.next_path)
    except OidcError as exc:
        db.rollback()
        # The flow stays consumed: a failed callback cannot be replayed.
        if state:
            oidc_service.discard_flow(db, state)
        audit_service.record(
            db,
            actor,
            "auth.login",
            outcome="failure",
            after={"via": "oidc", "reason": exc.reason},
        )
        db.commit()
        response = _redirect("/login?error=sso")
    response.delete_cookie(BINDING_COOKIE, path="/", secure=True, httponly=True, samesite="lax")
    return response
