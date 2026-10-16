"""Single sign-on settings from ``BACKEND_OIDC_*`` and ``BACKEND_LDAP_*`` environment variables.

Each variable maps to a field of the settings section (``BACKEND_OIDC_CLIENT_ID`` → ``client_id``)
and is validated by the same model as the administration API. A field defined here wins over the
UI and is shown read-only there. Secrets are only accepted as files (``*_FILE``), CA certificates
as ``*_CA_FILE``, scopes as comma-separated values, group mappings and admin groups as JSON.
Anything invalid or unknown stops the application at startup with the variable named.
"""

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.schemas.common import StrictModel
from app.schemas.settings import SECRET_FIELDS, LdapSettings, OidcSettings

PREFIXES: dict[str, tuple[str, type[StrictModel]]] = {
    "oidc": ("BACKEND_OIDC_", OidcSettings),
    "ldap": ("BACKEND_LDAP_", LdapSettings),
}
_LIST_FIELDS = frozenset({"scopes"})
# Group DNs contain commas: group lists are JSON, not comma-separated.
_JSON_FIELDS = frozenset({"group_mapping", "admin_groups"})


class SsoConfigurationError(RuntimeError):
    """Invalid single sign-on environment configuration (the message names the variable)."""


@dataclass(frozen=True)
class SsoEnvironment:
    """Validated values per section, only for the fields the environment defines."""

    sections: dict[str, dict[str, Any]] = field(default_factory=dict)

    def values(self, section: str) -> dict[str, Any]:
        return dict(self.sections.get(section, {}))

    def managed(self, section: str) -> frozenset[str]:
        return frozenset(self.sections.get(section, {}))


def _read_file(variable: str, path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise SsoConfigurationError(f"{variable}: cannot read {path}") from exc


def _raw_values(section: str, environ: Mapping[str, str]) -> dict[str, Any]:
    prefix, model = PREFIXES[section]
    secrets = set(SECRET_FIELDS.get(section, ()))
    known = {f"{prefix}{name.upper()}": name for name in model.model_fields}
    raw: dict[str, Any] = {}
    for variable, value in environ.items():
        if not variable.startswith(prefix) or value == "":
            continue
        suffix = variable.removeprefix(prefix)
        if suffix.endswith("_FILE") and suffix.removesuffix("_FILE").lower() in secrets:
            raw[suffix.removesuffix("_FILE").lower()] = _read_file(variable, value)
        elif suffix == "CA_FILE":
            raw["ca_pem"] = _read_file(variable, value)
        elif variable in known and known[variable] in secrets:
            raise SsoConfigurationError(
                f"{variable}: secrets are not read from variables, use {variable}_FILE"
            )
        elif variable in known and known[variable] != "ca_pem":
            name = known[variable]
            if name in _LIST_FIELDS:
                raw[name] = [item.strip() for item in value.replace(" ", ",").split(",") if item]
            elif name in _JSON_FIELDS:
                try:
                    raw[name] = json.loads(value)
                except json.JSONDecodeError as exc:
                    raise SsoConfigurationError(f"{variable}: not valid JSON") from exc
            else:
                raw[name] = value
        else:
            raise SsoConfigurationError(f"{variable}: unknown variable")
    return raw


def load(environ: Mapping[str, str] | None = None) -> SsoEnvironment:
    """Read and validate; raises ``SsoConfigurationError`` on the first problem."""
    environ = os.environ if environ is None else environ
    sections: dict[str, dict[str, Any]] = {}
    for section, (prefix, model) in PREFIXES.items():
        raw = _raw_values(section, environ)
        if not raw:
            continue
        try:
            validated = model.model_validate(raw).model_dump()
        except ValidationError as exc:
            problems = "; ".join(
                f"{prefix}{'_'.join(str(p) for p in error['loc']).upper() or '*'}: {error['msg']}"
                for error in exc.errors()
            )
            raise SsoConfigurationError(
                f"Invalid single sign-on configuration: {problems}"
            ) from exc
        sections[section] = {name: validated[name] for name in raw}
    return SsoEnvironment(sections)
