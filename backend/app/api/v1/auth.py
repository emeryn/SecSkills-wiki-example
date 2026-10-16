"""Sign-in flow: password, second factor, session info, step-up, sign-out, password reset."""

from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Response, status

from app.api.deps import (
    Ctx,
    CurrentActor,
    CurrentPrincipal,
    Db,
    any_session,
    authenticated,
    clear_session_cookie,
    mfa_pending,
    public,
    set_session_cookie,
)
from app.schemas.auth import (
    LoginRequest,
    PasswordResetConfirm,
    PasswordResetRequest,
    ReauthRequest,
    RecoveryCodeRequest,
    SessionInfo,
    SessionUser,
    StepResponse,
    TotpCode,
    WebAuthnAssertion,
)
from app.services import account_service, auth_service, mfa_service, session_service
from app.services.auth_service import SecondFactor
from app.services.user_profile import read_profile

router = APIRouter(prefix="/auth", tags=["auth"])


def _step(response: Response, ctx: Ctx, token: str, principal_session: Any) -> StepResponse:
    set_session_cookie(response, token, principal_session)
    return StepResponse(
        state=principal_session.state, csrf_token=session_service.csrf_for(ctx, principal_session)
    )


@router.post("/login", dependencies=[Depends(public)])
def login(
    body: LoginRequest, response: Response, db: Db, ctx: Ctx, actor: CurrentActor
) -> StepResponse:
    result = auth_service.login(db, ctx, body.username, body.password, actor)
    return _step(response, ctx, result.token, result.session)


@router.get("/session", dependencies=[Depends(any_session)])
def current_session(principal: CurrentPrincipal, db: Db, ctx: Ctx) -> SessionInfo:
    user, session = principal.user, principal.session
    profile = read_profile(ctx.cipher, user)
    mfa = mfa_service.status(db, user.id)
    methods: list[Any] = (["totp"] if mfa.totp else []) + (["webauthn"] if mfa.webauthn else [])
    return SessionInfo(
        state=session.state,
        user=SessionUser(
            id=user.id,
            username=user.username,
            display_name=profile.display_name,
            email=profile.email,
            role=user.global_role,
            auth_source=user.auth_source,
            permissions=sorted(principal.permissions),
        ),
        csrf_token=session_service.csrf_for(ctx, session),
        idle_expires_at=session.idle_expires_at,
        absolute_expires_at=session.absolute_expires_at,
        mfa_methods=methods,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(any_session)])
def logout(principal: CurrentPrincipal, response: Response, db: Db, actor: CurrentActor) -> None:
    auth_service.logout(db, principal, actor)
    clear_session_cookie(response)


def _second_factor(
    principal: CurrentPrincipal,
    response: Response,
    db: Db,
    ctx: Ctx,
    actor: CurrentActor,
    method: SecondFactor,
    payload: str | dict[str, Any],
) -> StepResponse:
    token = auth_service.verify_second_factor(db, ctx, principal, method, payload, actor)
    return _step(response, ctx, token, principal.session)


@router.post("/mfa/totp", dependencies=[Depends(mfa_pending)])
def mfa_totp(
    body: TotpCode,
    principal: CurrentPrincipal,
    response: Response,
    db: Db,
    ctx: Ctx,
    actor: CurrentActor,
) -> StepResponse:
    return _second_factor(principal, response, db, ctx, actor, "totp", body.code)


@router.post("/mfa/recovery", dependencies=[Depends(mfa_pending)])
def mfa_recovery(
    body: RecoveryCodeRequest,
    principal: CurrentPrincipal,
    response: Response,
    db: Db,
    ctx: Ctx,
    actor: CurrentActor,
) -> StepResponse:
    return _second_factor(principal, response, db, ctx, actor, "recovery_code", body.code)


@router.post("/mfa/webauthn/options", dependencies=[Depends(mfa_pending)])
def mfa_webauthn_options(principal: CurrentPrincipal, db: Db, ctx: Ctx) -> dict[str, Any]:
    options = mfa_service.authentication_options(db, ctx, principal.session, principal.user)
    db.commit()
    return options


@router.post("/mfa/webauthn", dependencies=[Depends(mfa_pending)])
def mfa_webauthn(
    body: WebAuthnAssertion,
    principal: CurrentPrincipal,
    response: Response,
    db: Db,
    ctx: Ctx,
    actor: CurrentActor,
) -> StepResponse:
    return _second_factor(principal, response, db, ctx, actor, "webauthn", body.credential)


@router.post("/reauth/webauthn/options", dependencies=[Depends(authenticated)])
def reauth_webauthn_options(principal: CurrentPrincipal, db: Db, ctx: Ctx) -> dict[str, Any]:
    options = mfa_service.authentication_options(db, ctx, principal.session, principal.user)
    db.commit()
    return options


@router.post("/reauth", dependencies=[Depends(authenticated)])
def reauth(
    body: ReauthRequest,
    principal: CurrentPrincipal,
    response: Response,
    db: Db,
    ctx: Ctx,
    actor: CurrentActor,
) -> StepResponse:
    factor: tuple[SecondFactor, str | dict[str, Any]] | None = None
    if body.totp_code:
        factor = ("totp", body.totp_code)
    elif body.recovery_code:
        factor = ("recovery_code", body.recovery_code)
    elif body.webauthn_credential:
        factor = ("webauthn", body.webauthn_credential)
    token = auth_service.reauthenticate(db, ctx, principal, body.password, factor, actor)
    return _step(response, ctx, token, principal.session)


@router.post(
    "/password-reset", status_code=status.HTTP_202_ACCEPTED, dependencies=[Depends(public)]
)
def password_reset(
    body: PasswordResetRequest, background: BackgroundTasks, db: Db, ctx: Ctx, actor: CurrentActor
) -> dict[str, str]:
    outcome = account_service.request_reset(db, ctx, body.email, actor)
    if outcome is not None:
        background.add_task(account_service.send_reset_email, ctx, *outcome)
    return {"status": "If the address belongs to an account, a reset link has been sent."}


@router.post(
    "/password-reset/confirm",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(public)],
)
def password_reset_confirm(
    body: PasswordResetConfirm, db: Db, ctx: Ctx, actor: CurrentActor
) -> None:
    account_service.confirm_reset(db, ctx, body.token, body.new_password, actor)
