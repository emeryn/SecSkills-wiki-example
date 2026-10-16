"""Sign-in, MFA, session and account schemas."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.common import Code, Email, Password, StrictModel, Token, Username

SessionState = Literal[
    "active", "mfa_required", "password_change_required", "mfa_enrollment_required"
]
WebAuthnPayload = dict[str, Any]


class LoginRequest(StrictModel):
    username: Username
    password: Password


class TotpCode(StrictModel):
    code: Code


class RecoveryCodeRequest(StrictModel):
    code: Code


class WebAuthnAssertion(StrictModel):
    credential: WebAuthnPayload = Field(json_schema_extra={"maxProperties": 10})


class ReauthRequest(StrictModel):
    password: Password
    totp_code: Code | None = None
    recovery_code: Code | None = None
    webauthn_credential: WebAuthnPayload | None = None


class PasswordResetRequest(StrictModel):
    email: Email


class PasswordResetConfirm(StrictModel):
    token: Token
    new_password: Password


class PasswordChange(StrictModel):
    current_password: Password
    new_password: Password


class SessionUser(BaseModel):
    id: uuid.UUID
    username: str
    display_name: str | None
    email: str | None
    role: str
    auth_source: Literal["local", "oidc", "ldap"]
    permissions: list[str]


class SessionInfo(BaseModel):
    state: SessionState
    user: SessionUser
    csrf_token: str
    idle_expires_at: datetime
    absolute_expires_at: datetime
    mfa_methods: list[Literal["totp", "webauthn"]]


class StepResponse(BaseModel):
    """Result of a sign-in step: the next state and the CSRF token of the rotated session."""

    state: SessionState
    csrf_token: str


class SessionSummary(BaseModel):
    id: uuid.UUID
    created_at: datetime
    last_seen_at: datetime
    ip: str | None
    user_agent: str
    current: bool


class TotpSetupResponse(BaseModel):
    secret: str
    otpauth_uri: str
    qr_png_data_uri: str


class RecoveryCodes(BaseModel):
    codes: list[str]


class WebAuthnRegistration(StrictModel):
    name: str = Field(min_length=1, max_length=64)
    credential: WebAuthnPayload


class SecurityKey(BaseModel):
    id: uuid.UUID
    name: str
    created_at: datetime
    last_used_at: datetime | None


class MfaStatusResponse(BaseModel):
    totp: bool
    security_keys: list[SecurityKey]
    recovery_codes_left: int


class EnrollmentResponse(StepResponse):
    recovery_codes: list[str]
