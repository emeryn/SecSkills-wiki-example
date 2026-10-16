"""FastAPI dependencies: database session, request metadata and access policies."""

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request, Response
from sqlalchemy.orm import Session

from app.core.context import AppContext
from app.core.csrf import SESSION_COOKIE
from app.core.errors import AppError
from app.core.logging import request_id_var
from app.core.permissions import (
    ANY_STATE,
    API_KEY,
    AUTHENTICATED,
    PUBLIC,
    RECENT_AUTH,
    AccessPolicy,
    Permission,
    permission,
    session_in,
)
from app.models import AuthSession
from app.services import session_service
from app.services.audit_service import Actor
from app.services.session_service import Principal


def get_context(request: Request) -> AppContext:
    context: AppContext = request.app.state.context
    return context


def get_db(request: Request) -> Iterator[Session]:
    with get_context(request).sessions() as db:
        try:
            yield db
        except Exception:
            db.rollback()
            raise


Db = Annotated[Session, Depends(get_db)]
Ctx = Annotated[AppContext, Depends(get_context)]


def get_actor(request: Request) -> Actor:
    principal: Principal | None = getattr(request.state, "principal", None)
    state = request.scope.get("state", {})
    return Actor(
        user_id=principal.user.id if principal else None,
        ip=state.get("client_ip"),
        user_agent=request.headers.get("user-agent", "")[:512],
        request_id=request_id_var.get(),
        ip_trusted=bool(state.get("client_ip_trusted")),
    )


class Access:
    """Route dependency enforcing an access policy; every route declares exactly one."""

    def __init__(self, policy: AccessPolicy) -> None:
        self.policy = policy

    def __call__(self, request: Request, db: Db, ctx: Ctx) -> Principal | None:
        policy = self.policy
        if not policy.authenticated:
            return None
        cookie = request.cookies.get(SESSION_COOKIE)
        principal = session_service.resolve(db, ctx, cookie) if cookie else None
        if principal is None:
            raise AppError(401, "UNAUTHENTICATED", "Sign in required")
        request.state.principal = principal
        if principal.session.state not in policy.states:
            raise AppError(
                403, "SESSION_INCOMPLETE", f"Complete sign-in first: {principal.session.state}"
            )
        if policy.permission is not None and policy.permission not in principal.permissions:
            raise AppError(403, "FORBIDDEN", "You do not have permission to do this")
        if policy.recent_auth and not session_service.recently_authenticated(
            ctx, principal.session
        ):
            raise AppError(401, "REAUTH_REQUIRED", "Confirm your identity to continue")
        return principal


public = Access(PUBLIC)
api_key = Access(API_KEY)
authenticated = Access(AUTHENTICATED)
recent_auth = Access(RECENT_AUTH)
any_session = Access(session_in(ANY_STATE, "any-session"))
mfa_pending = Access(session_in(frozenset({"mfa_required"}), "mfa-pending"))
password_change = Access(
    session_in(frozenset({"active", "password_change_required"}), "password-change")
)
enrollment = Access(session_in(frozenset({"active", "mfa_enrollment_required"}), "mfa-enrollment"))


def require(perm: Permission, *, recent: bool = False) -> Access:
    return Access(permission(perm, recent_auth=recent))


def principal_of(request: Request) -> Principal:
    found: Principal | None = getattr(request.state, "principal", None)
    if found is None:
        raise AppError(401, "UNAUTHENTICATED", "Sign in required")
    return found


CurrentPrincipal = Annotated[Principal, Depends(principal_of)]
CurrentActor = Annotated[Actor, Depends(get_actor)]


def set_session_cookie(response: Response, token: str, session: AuthSession) -> None:
    max_age = int((session.absolute_expires_at - session.last_seen_at).total_seconds())
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=max(max_age, 0),
        path="/",
        secure=True,
        httponly=True,
        samesite="lax",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/", secure=True, httponly=True, samesite="lax")
