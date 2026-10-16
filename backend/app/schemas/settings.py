"""Settings sections editable from the administration UI.

The same models validate stored values, request bodies and, for single sign-on, the
``BACKEND_OIDC_*`` / ``BACKEND_LDAP_*`` environment variables. Secret fields (SMTP password,
webhook secret, OIDC client secret, LDAP bind password) are write-only: responses carry ``••••``
plus the last four characters, and a request that omits the field keeps the stored value.
"""

from datetime import datetime
from typing import Annotated, Any, Literal, Self
from urllib.parse import urlsplit

from cryptography import x509
from pydantic import BaseModel, Field, StringConstraints, field_validator, model_validator

from app.schemas.common import Email, StrictModel, Username

SectionName = Literal[
    "syslog",
    "smtp",
    "webhook",
    "notifications",
    "privacy",
    "security",
    "oidc",
    "ldap",
    "llm",
    "mcp",
]
TestableSection = Literal["syslog", "smtp", "webhook", "oidc", "ldap", "llm"]
MODEL_PATTERN = r"^[A-Za-z0-9._:/-]{1,200}$"
SpaceRole = Literal["viewer", "editor", "space_admin"]
# Asymmetric only: "none" and shared-secret (HS*) algorithms are never accepted.
IdTokenAlgorithm = Literal[
    "RS256", "RS384", "RS512", "PS256", "PS384", "PS512", "ES256", "ES384", "ES512", "EdDSA"
]
CLAIM_PATTERN = r"^[A-Za-z0-9_:./-]{1,100}$"
ATTRIBUTE_PATTERN = r"^[A-Za-z][A-Za-z0-9-]{0,63}$"
DN_PATTERN = r"^[^\r\n\x00]*$"
LogLevelName = Literal["INFO", "WARNING", "ERROR", "CRITICAL"]

MAX_PEM_LENGTH = 65536


def _check_pem(value: str | None) -> str | None:
    if value is None or value.strip() == "":
        return None
    try:
        x509.load_pem_x509_certificates(value.encode())
    except ValueError as exc:
        raise ValueError("Not a PEM certificate bundle") from exc
    return value.strip() + "\n"


class _Section(StrictModel):
    @field_validator("ca_pem", mode="after", check_fields=False)
    @classmethod
    def _pem(cls, value: str | None) -> str | None:
        return _check_pem(value)


class SyslogSettings(_Section):
    """Remote syslog over TLS (RFC 5424 messages, RFC 5425 transport)."""

    enabled: bool = False
    host: str | None = Field(None, max_length=253)
    port: int = Field(6514, ge=1, le=65535)
    ca_pem: str | None = Field(None, max_length=MAX_PEM_LENGTH)
    app_name: str = Field("wiki", pattern=r"^[!-~]{1,48}$")
    forward_audit: bool = True
    min_level: LogLevelName = "WARNING"


class SmtpSettings(_Section):
    """Outbound email over SMTPS (implicit TLS) with certificate verification."""

    enabled: bool = False
    host: str | None = Field(None, max_length=253)
    port: int = Field(465, ge=1, le=65535)
    from_address: Email | None = None
    username: str | None = Field(None, max_length=254, pattern=r"^[^\r\n]*$")
    password: str | None = Field(None, max_length=1024)
    ca_pem: str | None = Field(None, max_length=MAX_PEM_LENGTH)


class WebhookSettings(_Section):
    """Notifications POSTed as JSON, signed with HMAC-SHA256 (``X-Signature``)."""

    enabled: bool = False
    url: str | None = Field(None, max_length=2000)
    secret: str | None = Field(None, min_length=32, max_length=256)
    ca_pem: str | None = Field(None, max_length=MAX_PEM_LENGTH)


class NotificationSettings(StrictModel):
    """What is sent through email and the webhook; both channels are throttled."""

    notify_errors: bool = True
    notify_security: bool = True
    email_recipients: list[Email] = Field(default_factory=list, max_length=10)


class PrivacySettings(StrictModel):
    """Masks email and IP addresses in logs, syslog messages and notifications."""

    mask_pii: bool = False


class SecuritySettings(StrictModel):
    """Honeytokens and outbound destinations."""

    honeytokens_enabled: bool = True
    decoy_usernames: list[Username] = Field(
        default_factory=lambda: ["administrator", "sysadmin"], max_length=20
    )
    # 0 keeps the IP blocked until an administrator unblocks it.
    block_minutes: int = Field(1440, ge=0, le=525600)
    allowed_private_networks: list[str] = Field(default_factory=list, max_length=20)
    # "admins_only": with single sign-on, only administrators sign in with a local password
    # (break-glass), and each such sign-in raises a critical alert.
    local_sign_in: Literal["all", "admins_only"] = "all"

    @field_validator("allowed_private_networks")
    @classmethod
    def _networks(cls, value: list[str]) -> list[str]:
        if any(len(item) > 50 for item in value):  # noqa: PLR2004
            raise ValueError("Network too long")
        return [item.strip() for item in value]


GroupName = Annotated[
    str, StringConstraints(min_length=1, max_length=500, pattern=r"^[^\r\n\x00]+$")
]


class GroupMapping(StrictModel):
    """Members of ``group`` (IdP group, or directory group DN or CN) get ``role`` in ``space``."""

    group: str = Field(min_length=1, max_length=500, pattern=r"^[^\r\n\x00]+$")
    space: str = Field(pattern=r"^[a-z0-9-]{1,40}$")
    role: SpaceRole


class OidcSettings(_Section):
    """OpenID Connect: authorization code flow with PKCE, ID token algorithm pinned."""

    enabled: bool = False
    display_name: str = Field("Single sign-on", min_length=1, max_length=50)
    issuer: str | None = Field(None, max_length=2000)
    client_id: str | None = Field(None, max_length=255, pattern=r"^[!-~]+$")
    client_secret: str | None = Field(None, max_length=1024)
    scopes: list[str] = Field(
        default_factory=lambda: ["openid", "profile", "email"], min_length=1, max_length=20
    )
    id_token_algorithm: IdTokenAlgorithm = "RS256"  # noqa: S105  # nosec B105
    username_claim: str = Field("preferred_username", pattern=CLAIM_PATTERN)
    email_claim: str = Field("email", pattern=CLAIM_PATTERN)
    name_claim: str = Field("name", pattern=CLAIM_PATTERN)
    groups_claim: str = Field("groups", pattern=CLAIM_PATTERN)
    auto_provision: bool = True
    group_mapping: list[GroupMapping] = Field(default_factory=list, max_length=200)
    # Members of any of these groups get the global administrator role (MFA still required).
    admin_groups: list[GroupName] = Field(default_factory=list, max_length=50)
    ca_pem: str | None = Field(None, max_length=MAX_PEM_LENGTH)

    @field_validator("issuer")
    @classmethod
    def _issuer(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parts = urlsplit(value)
        if parts.scheme != "https" or not parts.hostname or parts.query or parts.fragment:
            raise ValueError("The issuer must be an https URL without query or fragment")
        return value

    @field_validator("scopes")
    @classmethod
    def _scopes(cls, value: list[str]) -> list[str]:
        for scope in value:
            if not 1 <= len(scope) <= 64 or not scope.isprintable() or " " in scope:  # noqa: PLR2004
                raise ValueError("Invalid scope")
        if "openid" not in value:
            raise ValueError("The openid scope is required")
        return value


class LdapSettings(_Section):
    """Directory sign-in over LDAPS or StartTLS; certificates are always verified."""

    enabled: bool = False
    url: str | None = Field(None, max_length=500)
    start_tls: bool = False
    bind_dn: str | None = Field(None, max_length=500, pattern=DN_PATTERN)
    bind_password: str | None = Field(None, max_length=1024)
    user_base_dn: str | None = Field(None, max_length=500, pattern=DN_PATTERN)
    user_filter: str = Field(
        "(&(objectClass=person)(uid={username}))", max_length=500, pattern=r"^\(.*\)$"
    )
    username_attribute: str = Field("uid", pattern=ATTRIBUTE_PATTERN)
    email_attribute: str = Field("mail", pattern=ATTRIBUTE_PATTERN)
    name_attribute: str = Field("cn", pattern=ATTRIBUTE_PATTERN)
    group_base_dn: str | None = Field(None, max_length=500, pattern=DN_PATTERN)
    group_filter: str = Field(
        "(&(objectClass=groupOfNames)(member={user_dn}))", max_length=500, pattern=r"^\(.*\)$"
    )
    auto_provision: bool = True
    group_mapping: list[GroupMapping] = Field(default_factory=list, max_length=200)
    # Members of any of these groups get the global administrator role (MFA still required).
    admin_groups: list[GroupName] = Field(default_factory=list, max_length=50)
    ca_pem: str | None = Field(None, max_length=MAX_PEM_LENGTH)

    @field_validator("url")
    @classmethod
    def _url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parts = urlsplit(value)
        if parts.scheme not in ("ldaps", "ldap") or not parts.hostname:
            raise ValueError("Use ldaps://host[:port], or ldap://host[:port] with StartTLS")
        if parts.path not in ("", "/") or parts.query or parts.username:
            raise ValueError("Use ldaps://host[:port], or ldap://host[:port] with StartTLS")
        return value

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        # Clear-text binds are never possible: ldap:// requires StartTLS.
        if self.url is not None and self.url.startswith("ldap://") and not self.start_tls:
            raise ValueError("ldap:// is only allowed with StartTLS")
        if "{username}" not in self.user_filter:
            raise ValueError("The user filter must contain {username}")
        if "{user_dn}" not in self.group_filter:
            raise ValueError("The group filter must contain {user_dn}")
        return self


class LlmSettings(_Section):
    """Inference server for "Ask the wiki" (Ollama API), models and generation limits."""

    enabled: bool = False
    # https, or http only towards an allowlisted private network (checked when saved and used).
    url: str | None = Field(None, max_length=2000)
    api_key: str | None = Field(None, max_length=1024)
    ca_pem: str | None = Field(None, max_length=MAX_PEM_LENGTH)
    # Optional HTTPS proxy (CONNECT); the target is still SSRF-checked.
    proxy_url: str | None = Field(None, max_length=500)
    chat_model: str | None = Field(None, pattern=MODEL_PATTERN)
    embedding_model: str | None = Field(None, pattern=MODEL_PATTERN)
    # Pinned when the settings are saved: a model whose digest changes is refused.
    model_digests: dict[str, str] = Field(default_factory=dict, max_length=2)
    temperature: float = Field(0.2, ge=0, le=2)
    top_p: float = Field(0.9, gt=0, le=1)
    max_tokens: int = Field(1024, ge=64, le=8192)
    context_window: int = Field(8192, ge=2048, le=131072)
    retrieval_chunks: int = Field(6, ge=1, le=12)
    min_similarity: float = Field(0.3, ge=0, le=1)
    daily_token_quota: int = Field(100_000, ge=1_000, le=10_000_000)
    requests_per_minute: int = Field(6, ge=1, le=60)
    # Questions and answers stay out of the logs unless enabled (then PII masking applies).
    log_prompts: bool = False

    @field_validator("url", "proxy_url")
    @classmethod
    def _http_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parts = urlsplit(value)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise ValueError("Use an http(s) URL")
        if parts.username or parts.password or parts.query or parts.fragment:
            raise ValueError("No credentials, query or fragment in the URL")
        return value.rstrip("/")


class McpSettings(StrictModel):
    """MCP endpoints for AI clients, authenticated by API keys."""

    user_enabled: bool = True
    # Administration tools: off unless explicitly enabled; destructive ones need confirm=true.
    admin_enabled: bool = False
    requests_per_minute: int = Field(60, ge=1, le=600)


SECTION_MODELS: dict[str, type[StrictModel]] = {
    "syslog": SyslogSettings,
    "smtp": SmtpSettings,
    "webhook": WebhookSettings,
    "notifications": NotificationSettings,
    "privacy": PrivacySettings,
    "security": SecuritySettings,
    "oidc": OidcSettings,
    "ldap": LdapSettings,
    "llm": LlmSettings,
    "mcp": McpSettings,
}
SECRET_FIELDS: dict[str, tuple[str, ...]] = {
    "smtp": ("password",),
    "webhook": ("secret",),
    "oidc": ("client_secret",),
    "ldap": ("bind_password",),
    "llm": ("api_key",),
}
# Checked after secrets are merged: a request may omit a secret to keep the stored one.
REQUIRED_WHEN_ENABLED: dict[str, tuple[str, ...]] = {
    "syslog": ("host",),
    "smtp": ("host", "from_address"),
    "webhook": ("url", "secret"),
    "oidc": ("issuer", "client_id", "client_secret"),
    "ldap": ("url", "user_base_dn"),
    "llm": ("url", "chat_model", "embedding_model"),
}
# Set by the server, never from a request body.
SERVER_FIELDS: dict[str, tuple[str, ...]] = {"llm": ("model_digests",)}


class SettingsOut(BaseModel):
    section: SectionName
    values: dict[str, Any]
    managed_by_environment: bool
    # Fields set by environment variables: shown read-only, refused in updates.
    managed_fields: list[str] = Field(default_factory=list)
    updated_at: datetime | None
    updated_by: str | None
    # Read-only context shown next to the form (e.g. the trusted proxy count).
    info: dict[str, Any] = Field(default_factory=dict)


class CheckResult(BaseModel):
    ok: bool
    message: str
