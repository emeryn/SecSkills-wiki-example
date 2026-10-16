"""Settings administration: validation (SSRF included), write-only secrets, audit, "Send test"."""

import smtplib
import ssl
from datetime import UTC, datetime
from typing import Any, cast
from urllib.parse import urlsplit

from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.context import AppContext
from app.core.errors import AppError
from app.core.mailer import MailerDisabledError
from app.core.outbound_url import OutboundUrlError, parse_networks, resolve, resolve_url
from app.core.rate_limit import RateLimiter
from app.core.runtime_settings import decrypt_section, encrypt_section
from app.llm.provider import ProviderError
from app.models import Setting, Space, User
from app.schemas.settings import (
    REQUIRED_WHEN_ENABLED,
    SECRET_FIELDS,
    SECTION_MODELS,
    SERVER_FIELDS,
    CheckResult,
    LlmSettings,
    SecuritySettings,
    SettingsOut,
)
from app.services import (
    audit_service,
    ldap_service,
    llm_config,
    oidc_service,
    sso_config,
    syslog_forwarder,
)
from app.services.audit_service import Actor
from app.services.ldap_service import DirectoryUnavailableError
from app.services.llm_config import LlmUnavailableError
from app.services.notifier import Channel, Notifier, check_event
from app.services.oidc_service import OidcError
from app.services.session_service import Principal
from app.services.sso_config import SsoSection
from app.services.user_profile import read_profile
from app.services.webhook import WebhookError

MASK = "••••"
_test_limiter = RateLimiter(max_events=3, window_seconds=60)


def mask_secret(value: str | None) -> str | None:
    if not value:
        return None
    return MASK + value[-4:] if len(value) >= 12 else MASK  # noqa: PLR2004


def _row(db: Session, section: str) -> Setting | None:
    return db.get(Setting, section)


def _stored_values(db: Session, ctx: AppContext, section: str) -> dict[str, Any]:
    row = _row(db, section)
    if row is None:
        return {}
    try:
        return decrypt_section(ctx.cipher, row)
    except ValueError, TypeError:
        return {}


def _model(section: str, values: dict[str, Any]) -> BaseModel:
    try:
        return SECTION_MODELS[section].model_validate(values)
    except ValidationError:
        return SECTION_MODELS[section]()


def _public(section: str, values: dict[str, Any]) -> dict[str, Any]:
    shown = dict(values)
    for name in SECRET_FIELDS.get(section, ()):
        shown[name] = mask_secret(shown.get(name))
    return shown


def _audit_view(section: str, values: dict[str, Any]) -> dict[str, Any]:
    view = dict(values)
    for name in SECRET_FIELDS.get(section, ()):
        view[name] = "[set]" if view.get(name) else None
    if view.get("ca_pem"):
        view["ca_pem"] = "[certificate]"
    return view


def _env_smtp(ctx: AppContext) -> dict[str, Any]:
    settings = ctx.settings
    return {
        "enabled": True,
        "host": settings.smtp_host,
        "port": settings.smtp_port,
        "from_address": settings.smtp_from,
        "username": settings.smtp_username,
        "password": MASK if settings.smtp_password_file else None,
        "ca_pem": None,
    }


def _effective_values(db: Session, ctx: AppContext, section: str) -> dict[str, Any]:
    """Stored values with the environment's on top (single sign-on sections)."""
    values = _model(section, _stored_values(db, ctx, section)).model_dump()
    values.update(ctx.sso_env.values(section))
    return values


def section_out(db: Session, ctx: AppContext, section: str) -> SettingsOut:
    managed = section == "smtp" and ctx.mailer.managed_by_environment
    row = _row(db, section)
    values = _env_smtp(ctx) if managed else _public(section, _effective_values(db, ctx, section))
    updated_by = None
    if row is not None and row.updated_by is not None:
        updated_by = db.scalar(select(User.username).where(User.id == row.updated_by))
    info: dict[str, Any] = {}
    if section == "security":
        info["trusted_proxy_count"] = ctx.settings.trusted_proxy_count
    return SettingsOut(
        section=section,
        values=values,
        managed_by_environment=managed,
        managed_fields=sorted(ctx.sso_env.managed(section)),
        updated_at=row.updated_at if row is not None else None,
        updated_by=updated_by,
        info=info,
    )


def _refuse(message: str, field: str | None = None) -> AppError:
    details = {"field": field} if field else None
    return AppError(422, "SETTING_REJECTED", message, details)


def _allowed_networks(db: Session, ctx: AppContext) -> list[str]:
    security = cast(SecuritySettings, _model("security", _stored_values(db, ctx, "security")))
    return security.allowed_private_networks


_DESTINATION_FIELD = {"webhook": "url", "oidc": "issuer", "ldap": "url", "llm": "url"}


def _check_destination(db: Session, ctx: AppContext, section: str, values: dict[str, Any]) -> None:
    """Refuse destinations the outbound policy would refuse at delivery time."""
    if not values.get("enabled"):
        return
    field = _DESTINATION_FIELD.get(section, "host")
    try:
        if section in ("oidc", "ldap"):
            allowed = sso_config.allowed_networks(ctx, cast(SsoSection, section))
        else:
            allowed = parse_networks(_allowed_networks(db, ctx))
        if section in ("webhook", "oidc"):
            resolve_url(str(values[field]), allowed)
        elif section == "ldap":
            parts = urlsplit(str(values["url"]))
            default_port = 636 if parts.scheme == "ldaps" else 389
            resolve(parts.hostname or "", parts.port or default_port, allowed)
        elif section in ("syslog", "smtp"):
            resolve(str(values["host"]), int(values["port"]), allowed)
        elif section == "llm":
            config = LlmSettings.model_validate(values)
            llm_config.destination(config, allowed)
            llm_config.proxy_destination(config, allowed)
    except OutboundUrlError as exc:
        raise _refuse(exc.reason, field) from exc


def _approve_models(ctx: AppContext, values: dict[str, Any]) -> dict[str, str]:
    """Pin the digests of the chosen models (they must exist and be GGUF or safetensors)."""
    if not values.get("enabled"):
        return {}
    config = LlmSettings.model_validate(values)
    try:
        return llm_config.pin(llm_config.make_provider(ctx, config), config)
    except ValueError as exc:
        raise _refuse(str(exc), "chat_model") from exc
    except (ProviderError, LlmUnavailableError) as exc:
        raise _refuse(
            "The inference server could not be reached to approve the models", "url"
        ) from exc


def _check_group_mapping(db: Session, values: dict[str, Any]) -> None:
    keys = {rule["space"] for rule in values.get("group_mapping") or []}
    if not keys:
        return
    found = set(db.scalars(select(Space.key).where(Space.key.in_(keys))).all())
    missing = sorted(keys - found)
    if missing:
        raise _refuse(f"Unknown space: {', '.join(missing)}", "group_mapping")


def save(
    db: Session,
    ctx: AppContext,
    section: str,
    body: BaseModel,
    actor: Actor,
) -> SettingsOut:
    """Replace a section. Omitted secrets keep their stored value; ``null`` clears them."""
    if section == "smtp" and ctx.mailer.managed_by_environment:
        raise AppError(409, "MANAGED_BY_ENVIRONMENT", "Email is configured by the environment")
    managed = ctx.sso_env.managed(section)
    conflict = sorted(managed & body.model_fields_set)
    if conflict:
        raise AppError(
            409,
            "MANAGED_BY_ENVIRONMENT",
            "These settings are defined by environment variables",
            {"fields": conflict},
        )
    current = _stored_values(db, ctx, section)
    values = body.model_dump()
    for name in SECRET_FIELDS.get(section, ()):
        if name not in body.model_fields_set:
            values[name] = current.get(name)
    default = SECTION_MODELS[section]().model_dump()
    for name in (*managed, *SERVER_FIELDS.get(section, ())):
        values[name] = current.get(name, default[name])
    effective = {**values, **ctx.sso_env.values(section)}
    try:
        SECTION_MODELS[section].model_validate(effective)
    except ValidationError as exc:
        field = ".".join(str(part) for part in exc.errors()[0]["loc"]) or None
        raise _refuse(str(exc.errors()[0]["msg"]), field) from exc
    if effective.get("enabled"):
        for name in REQUIRED_WHEN_ENABLED.get(section, ()):
            if not effective.get(name):
                raise _refuse(f"{name} is required when enabled", name)
    if section == "security":
        try:
            parse_networks(values["allowed_private_networks"])
        except OutboundUrlError as exc:
            raise _refuse(exc.reason, "allowed_private_networks") from exc
    _check_destination(db, ctx, section, effective)
    _check_group_mapping(db, effective)
    if section == "llm":
        values["model_digests"] = _approve_models(ctx, effective)

    row = _row(db, section) or Setting(key=section)
    before = _audit_view(section, _model(section, current).model_dump()) if current else None
    encrypt_section(ctx.cipher, row, values)
    row.updated_by = actor.user_id
    row.updated_at = datetime.now(UTC)
    db.add(row)
    audit_service.record(
        db,
        actor,
        "settings.updated",
        target_type="settings",
        target_id=section,
        before=before,
        after=_audit_view(section, values),
    )
    db.commit()
    ctx.runtime.refresh()
    return section_out(db, ctx, section)


def reset(db: Session, ctx: AppContext, section: str, actor: Actor) -> SettingsOut:
    if section == "smtp" and ctx.mailer.managed_by_environment:
        raise AppError(409, "MANAGED_BY_ENVIRONMENT", "Email is configured by the environment")
    row = _row(db, section)
    if row is not None:
        before = _audit_view(
            section, _model(section, _stored_values(db, ctx, section)).model_dump()
        )
        db.delete(row)
        audit_service.record(
            db, actor, "settings.reset", target_type="settings", target_id=section, before=before
        )
        db.commit()
        ctx.runtime.refresh()
    return section_out(db, ctx, section)


# Most specific first; messages are safe to show (no server response is echoed).
_FAILURES: tuple[tuple[type[BaseException], str], ...] = (
    (ssl.SSLError, "TLS verification failed (check the CA certificate)"),
    (smtplib.SMTPAuthenticationError, "The SMTP server refused the credentials"),
    (smtplib.SMTPException, "The SMTP server refused the message"),
    (TimeoutError, "Connection timed out"),
)


def _failure_message(exc: Exception) -> str:
    if isinstance(exc, OutboundUrlError):
        return exc.reason
    if isinstance(exc, WebhookError | MailerDisabledError):
        return str(exc) or "Not configured"
    return next((text for kind, text in _FAILURES if isinstance(exc, kind)), "Connection failed")


def _test_recipient(db: Session, ctx: AppContext, principal: Principal) -> str:
    own = read_profile(ctx.cipher, principal.user).email
    recipients = ctx.runtime.snapshot().notifications.email_recipients
    recipient = own or (recipients[0] if recipients else None)
    if recipient is None:
        raise AppError(
            409, "NO_RECIPIENT", "Add an email address to your account or a notification recipient"
        )
    return recipient


def run_test(
    db: Session, ctx: AppContext, section: str, principal: Principal, actor: Actor
) -> CheckResult:
    """Deliver one test message with the saved settings (throttled per administrator)."""
    _test_limiter.check(f"{principal.user.id}:{section}")
    snapshot = ctx.runtime.refresh()
    if section in ("oidc", "ldap"):
        result = _check_sso(ctx, cast(SsoSection, section))
        _record_test(db, actor, section, result)
        return result
    if section == "llm":
        result = _check_llm(ctx)
        _record_test(db, actor, section, result)
        return result
    enabled = {
        "syslog": snapshot.syslog.enabled,
        "smtp": ctx.mailer.enabled,
        "webhook": snapshot.webhook.enabled,
    }[section]
    if not enabled:
        raise AppError(409, "NOT_ENABLED", "Enable and save these settings first")
    recipient = _test_recipient(db, ctx, principal) if section == "smtp" else None
    try:
        allowed = parse_networks(snapshot.security.allowed_private_networks)
        if section == "syslog":
            syslog_forwarder.send_test(snapshot.syslog, allowed, ctx.settings.public_hostname)
        else:
            notifier = Notifier(ctx.runtime, ctx.mailer)
            channel: Channel = "email" if section == "smtp" else "webhook"
            event = check_event(principal.user.username)
            notifier.send(channel, snapshot, event, recipients=[recipient] if recipient else None)
        result = CheckResult(ok=True, message="Test message sent")
    except (OSError, OutboundUrlError, WebhookError, smtplib.SMTPException) as exc:
        result = CheckResult(ok=False, message=_failure_message(exc))
    _record_test(db, actor, section, result)
    return result


_OIDC_FAILURES = {
    "idp_unreachable": "The identity provider could not be reached",
    "issuer_mismatch": "The discovery document names another issuer",
    "no_signing_keys": "The identity provider publishes no signing key",
    "invalid_json": "The identity provider answered something that is not JSON",
}


def _check_sso(ctx: AppContext, section: SsoSection) -> CheckResult:
    """Connection test: OIDC discovery and keys, or LDAP bind and a sample search."""
    allowed = sso_config.allowed_networks(ctx, section)
    if section == "oidc":
        oidc = sso_config.oidc(ctx)
        if not oidc.enabled:
            raise AppError(409, "NOT_ENABLED", "Enable and save these settings first")
        try:
            message = oidc_service.check(oidc, oidc_service.make_transport(oidc, allowed))
        except OidcError as exc:
            reason = _OIDC_FAILURES.get(
                exc.reason, f"Identity provider check failed ({exc.reason})"
            )
            return CheckResult(ok=False, message=reason)
        return CheckResult(ok=True, message=message)
    directory = sso_config.ldap(ctx)
    if not directory.enabled:
        raise AppError(409, "NOT_ENABLED", "Enable and save these settings first")
    try:
        message = ldap_service.check(directory, allowed)
    except (DirectoryUnavailableError, OutboundUrlError) as exc:
        return CheckResult(
            ok=False,
            message=_failure_message(exc) if isinstance(exc, OutboundUrlError) else str(exc),
        )
    return CheckResult(ok=True, message=message)


def _check_llm(ctx: AppContext) -> CheckResult:
    """Server reachable and approved models unchanged."""
    if not ctx.runtime.snapshot().llm.enabled:
        raise AppError(409, "NOT_ENABLED", "Enable and save these settings first")
    llm_config.clear_cache()
    try:
        config, provider = llm_config.ready(ctx)
        version = provider.health()
    except LlmUnavailableError as exc:
        return CheckResult(ok=False, message=exc.message)
    except ProviderError:
        return CheckResult(ok=False, message="The inference server is unavailable")
    return CheckResult(
        ok=True,
        message=f"Inference server {version}; {config.chat_model} and "
        f"{config.embedding_model} available and unchanged",
    )


def _record_test(db: Session, actor: Actor, section: str, result: CheckResult) -> None:
    audit_service.record(
        db,
        actor,
        "settings.tested",
        outcome="success" if result.ok else "failure",
        target_type="settings",
        target_id=section,
        after={"message": result.message},
    )
    db.commit()
