"""The signed-in user's own account: password, second factors, sessions."""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Response, status

from app.api.deps import (
    Ctx,
    CurrentActor,
    CurrentPrincipal,
    Db,
    authenticated,
    enrollment,
    password_change,
    recent_auth,
    set_session_cookie,
)
from app.core.errors import AppError
from app.schemas.admin import Count
from app.schemas.auth import (
    EnrollmentResponse,
    MfaStatusResponse,
    PasswordChange,
    RecoveryCodes,
    SecurityKey,
    SessionSummary,
    StepResponse,
    TotpCode,
    TotpSetupResponse,
    WebAuthnRegistration,
)
from app.services import account_service, audit_service, mfa_service, session_service
from app.services.session_service import Principal

router = APIRouter(prefix="/me", tags=["account"])


def _require_recent(ctx: Ctx, principal: Principal) -> None:
    """Adding a factor needs a fresh password check, so a stolen session cannot persist itself."""
    if not session_service.recently_authenticated(ctx, principal.session):
        raise AppError(401, "REAUTH_REQUIRED", "Confirm your identity to continue")


@router.post("/password", dependencies=[Depends(password_change)])
def change_password(
    body: PasswordChange,
    principal: CurrentPrincipal,
    response: Response,
    db: Db,
    ctx: Ctx,
    actor: CurrentActor,
) -> StepResponse:
    token = account_service.change_password(
        db, ctx, principal, body.current_password, body.new_password, actor
    )
    set_session_cookie(response, token, principal.session)
    return StepResponse(
        state=principal.session.state,
        csrf_token=session_service.csrf_for(ctx, principal.session),
    )


@router.get("/mfa", dependencies=[Depends(enrollment)])
def mfa_status(principal: CurrentPrincipal, db: Db) -> MfaStatusResponse:
    current = mfa_service.status(db, principal.user.id)
    return MfaStatusResponse(
        totp=current.totp,
        security_keys=[
            SecurityKey(id=k.id, name=k.name, created_at=k.created_at, last_used_at=k.last_used_at)
            for k in current.webauthn
        ],
        recovery_codes_left=current.recovery_codes_left,
    )


@router.post("/mfa/totp", dependencies=[Depends(enrollment)])
def totp_setup(principal: CurrentPrincipal, db: Db, ctx: Ctx) -> TotpSetupResponse:
    _require_recent(ctx, principal)
    setup = mfa_service.start_totp_setup(db, ctx, principal.user)
    db.commit()
    return TotpSetupResponse(
        secret=setup.secret, otpauth_uri=setup.otpauth_uri, qr_png_data_uri=setup.qr_png_data_uri
    )


def _enrolled(
    principal: Principal,
    response: Response,
    db: Db,
    ctx: Ctx,
    actor: CurrentActor,
    method: str,
    codes: list[str],
) -> EnrollmentResponse:
    token = account_service.mfa_enrolled(db, ctx, principal, method, actor)
    set_session_cookie(response, token, principal.session)
    return EnrollmentResponse(
        state=principal.session.state,
        csrf_token=session_service.csrf_for(ctx, principal.session),
        recovery_codes=codes,
    )


@router.post("/mfa/totp/confirm", dependencies=[Depends(enrollment)])
def totp_confirm(
    body: TotpCode,
    principal: CurrentPrincipal,
    response: Response,
    db: Db,
    ctx: Ctx,
    actor: CurrentActor,
) -> EnrollmentResponse:
    _require_recent(ctx, principal)
    codes = mfa_service.confirm_totp(db, ctx, principal.user, body.code)
    return _enrolled(principal, response, db, ctx, actor, "totp", codes)


@router.delete(
    "/mfa/totp", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(recent_auth)]
)
def totp_remove(principal: CurrentPrincipal, db: Db, actor: CurrentActor) -> None:
    mfa_service.remove_totp(db, principal.user)
    audit_service.record(
        db,
        actor,
        "account.mfa_removed",
        target_type="user",
        target_id=principal.user.id,
        before={"method": "totp"},
    )
    db.commit()


@router.post("/mfa/webauthn/options", dependencies=[Depends(enrollment)])
def webauthn_options(principal: CurrentPrincipal, db: Db, ctx: Ctx) -> dict[str, Any]:
    _require_recent(ctx, principal)
    options = mfa_service.registration_options(db, ctx, principal.session, principal.user)
    db.commit()
    return options


@router.post("/mfa/webauthn", dependencies=[Depends(enrollment)])
def webauthn_register(
    body: WebAuthnRegistration,
    principal: CurrentPrincipal,
    response: Response,
    db: Db,
    ctx: Ctx,
    actor: CurrentActor,
) -> EnrollmentResponse:
    _require_recent(ctx, principal)
    had_codes = mfa_service.status(db, principal.user.id).recovery_codes_left > 0
    mfa_service.register_credential(
        db, ctx, principal.session, principal.user, body.name, body.credential
    )
    codes = [] if had_codes else mfa_service.regenerate_recovery_codes(db, principal.user)
    return _enrolled(principal, response, db, ctx, actor, "webauthn", codes)


@router.delete(
    "/mfa/webauthn/{key_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(recent_auth)],
)
def webauthn_remove(
    key_id: uuid.UUID, principal: CurrentPrincipal, db: Db, actor: CurrentActor
) -> None:
    removed = mfa_service.remove_webauthn(db, principal.user, key_id)
    audit_service.record(
        db,
        actor,
        "account.mfa_removed",
        target_type="user",
        target_id=principal.user.id,
        before={"method": "webauthn", "name": removed.name},
    )
    db.commit()


@router.post("/mfa/recovery-codes", dependencies=[Depends(recent_auth)])
def recovery_codes(principal: CurrentPrincipal, db: Db, actor: CurrentActor) -> RecoveryCodes:
    if not mfa_service.has_mfa(db, principal.user.id):
        raise AppError(409, "NO_SECOND_FACTOR", "Enroll a second factor first")
    codes = mfa_service.regenerate_recovery_codes(db, principal.user)
    audit_service.record(
        db,
        actor,
        "account.recovery_codes_regenerated",
        target_type="user",
        target_id=principal.user.id,
    )
    db.commit()
    return RecoveryCodes(codes=codes)


@router.get("/sessions", dependencies=[Depends(authenticated)])
def sessions(principal: CurrentPrincipal, db: Db) -> list[SessionSummary]:
    return [
        SessionSummary(
            id=s.id,
            created_at=s.created_at,
            last_seen_at=s.last_seen_at,
            ip=str(s.ip) if s.ip else None,
            user_agent=s.user_agent,
            current=s.id == principal.session.id,
        )
        for s in account_service.list_sessions(db, principal)
    ]


@router.delete(
    "/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(authenticated)],
)
def revoke_session(
    session_id: uuid.UUID, principal: CurrentPrincipal, db: Db, actor: CurrentActor
) -> None:
    account_service.revoke_session(db, principal, session_id, actor)


@router.post("/sessions/revoke-others", dependencies=[Depends(authenticated)])
def revoke_others(principal: CurrentPrincipal, db: Db, actor: CurrentActor) -> Count:
    return Count(count=account_service.revoke_other_sessions(db, principal, actor))
