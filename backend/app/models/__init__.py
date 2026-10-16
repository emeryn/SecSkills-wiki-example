"""ORM models. Importing this package registers every table on ``Base.metadata``."""

from app.models.admin import BlockedIp, ServerError, Setting
from app.models.api_key import ApiKey
from app.models.audit import AuditEvent
from app.models.auth import (
    AuthSession,
    AuthThrottle,
    KnownDevice,
    OidcFlow,
    PasswordResetToken,
    RecoveryCode,
    TotpCredential,
    WebAuthnCredential,
)
from app.models.base import Base
from app.models.content import Attachment, Favorite, Page, Revision, Space, SpaceMember
from app.models.idempotency import IdempotencyKey
from app.models.llm import LlmPrompt, LlmUsage, PageChunk
from app.models.user import Group, GroupMember, User

__all__ = [
    "ApiKey",
    "Attachment",
    "AuditEvent",
    "AuthSession",
    "AuthThrottle",
    "Base",
    "BlockedIp",
    "Favorite",
    "Group",
    "GroupMember",
    "IdempotencyKey",
    "KnownDevice",
    "LlmPrompt",
    "LlmUsage",
    "OidcFlow",
    "Page",
    "PageChunk",
    "PasswordResetToken",
    "RecoveryCode",
    "Revision",
    "ServerError",
    "Setting",
    "Space",
    "SpaceMember",
    "TotpCredential",
    "User",
    "WebAuthnCredential",
]
