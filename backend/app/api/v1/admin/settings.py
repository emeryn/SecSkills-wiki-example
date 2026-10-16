"""Settings sections: syslog, SMTPS, webhook, notifications, privacy, security, OIDC, LDAP."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.deps import Ctx, CurrentActor, CurrentPrincipal, Db, require
from app.core.permissions import Permission
from app.schemas.settings import (
    CheckResult,
    LdapSettings,
    LlmSettings,
    McpSettings,
    NotificationSettings,
    OidcSettings,
    PrivacySettings,
    SectionName,
    SecuritySettings,
    SettingsOut,
    SmtpSettings,
    SyslogSettings,
    TestableSection,
    WebhookSettings,
)
from app.services import settings_service

router = APIRouter(prefix="/settings", tags=["admin"])

manage = require(Permission.SETTINGS_MANAGE)
# Changing where logs and alerts go, or the honeytokens, needs a fresh confirmation.
manage_recent = require(Permission.SETTINGS_MANAGE, recent=True)


@router.get("/{section}", dependencies=[Depends(manage)])
def get_section(section: SectionName, db: Db, ctx: Ctx) -> SettingsOut:
    return settings_service.section_out(db, ctx, section)


def _put(
    section: SectionName, body: BaseModel, db: Db, ctx: Ctx, actor: CurrentActor
) -> SettingsOut:
    return settings_service.save(db, ctx, section, body, actor)


@router.put("/syslog", dependencies=[Depends(manage_recent)])
def put_syslog(body: SyslogSettings, db: Db, ctx: Ctx, actor: CurrentActor) -> SettingsOut:
    return _put("syslog", body, db, ctx, actor)


@router.put("/smtp", dependencies=[Depends(manage_recent)])
def put_smtp(body: SmtpSettings, db: Db, ctx: Ctx, actor: CurrentActor) -> SettingsOut:
    return _put("smtp", body, db, ctx, actor)


@router.put("/webhook", dependencies=[Depends(manage_recent)])
def put_webhook(body: WebhookSettings, db: Db, ctx: Ctx, actor: CurrentActor) -> SettingsOut:
    return _put("webhook", body, db, ctx, actor)


@router.put("/notifications", dependencies=[Depends(manage)])
def put_notifications(
    body: NotificationSettings, db: Db, ctx: Ctx, actor: CurrentActor
) -> SettingsOut:
    return _put("notifications", body, db, ctx, actor)


@router.put("/privacy", dependencies=[Depends(manage)])
def put_privacy(body: PrivacySettings, db: Db, ctx: Ctx, actor: CurrentActor) -> SettingsOut:
    return _put("privacy", body, db, ctx, actor)


@router.put("/security", dependencies=[Depends(manage_recent)])
def put_security(body: SecuritySettings, db: Db, ctx: Ctx, actor: CurrentActor) -> SettingsOut:
    return _put("security", body, db, ctx, actor)


@router.put("/oidc", dependencies=[Depends(manage_recent)])
def put_oidc(body: OidcSettings, db: Db, ctx: Ctx, actor: CurrentActor) -> SettingsOut:
    return _put("oidc", body, db, ctx, actor)


@router.put("/ldap", dependencies=[Depends(manage_recent)])
def put_ldap(body: LdapSettings, db: Db, ctx: Ctx, actor: CurrentActor) -> SettingsOut:
    return _put("ldap", body, db, ctx, actor)


@router.put("/llm", dependencies=[Depends(manage_recent)])
def put_llm(body: LlmSettings, db: Db, ctx: Ctx, actor: CurrentActor) -> SettingsOut:
    return _put("llm", body, db, ctx, actor)


@router.put("/mcp", dependencies=[Depends(manage_recent)])
def put_mcp(body: McpSettings, db: Db, ctx: Ctx, actor: CurrentActor) -> SettingsOut:
    return _put("mcp", body, db, ctx, actor)


@router.delete("/{section}", dependencies=[Depends(manage_recent)])
def reset_section(section: SectionName, db: Db, ctx: Ctx, actor: CurrentActor) -> SettingsOut:
    """Back to the defaults."""
    return settings_service.reset(db, ctx, section, actor)


@router.post("/{section}/test", dependencies=[Depends(manage)])
def test_section(
    section: TestableSection,
    principal: CurrentPrincipal,
    db: Db,
    ctx: Ctx,
    actor: CurrentActor,
) -> CheckResult:
    """Send one message (or, for OIDC and LDAP, test the connection) with the saved settings."""
    return settings_service.run_test(db, ctx, section, principal, actor)
