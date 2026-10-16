"""BACKEND_OIDC_* / BACKEND_LDAP_*: validated by the shared schema; invalid values stop startup."""

from pathlib import Path

import pytest
from sqlalchemy import Engine

from app.core.config import Settings
from app.core.secrets import FileSecretsProvider
from app.core.sso_env import SsoConfigurationError, load
from app.main import create_app

ISSUER = "https://idp.example.com/realms/wiki"


def test_values_secrets_lists_and_mappings(tmp_path: Path) -> None:
    secret = tmp_path / "client_secret"
    secret.write_text("s3cret-from-a-file\n")
    env = load(
        {
            "BACKEND_OIDC_ENABLED": "true",
            "BACKEND_OIDC_ISSUER": ISSUER,
            "BACKEND_OIDC_CLIENT_ID": "wiki",
            "BACKEND_OIDC_CLIENT_SECRET_FILE": str(secret),
            "BACKEND_OIDC_SCOPES": "openid, profile groups",
            "BACKEND_OIDC_GROUP_MAPPING": '[{"group": "eng", "space": "docs", "role": "editor"}]',
            "BACKEND_LDAP_URL": "ldap://ldap.example.com",
            "BACKEND_LDAP_START_TLS": "true",
            "BACKEND_LDAP_ADMIN_GROUPS": '["cn=wiki-admins,ou=groups,dc=example,dc=com"]',
            "UNRELATED": "ignored",
        }
    )
    oidc = env.values("oidc")
    assert oidc["client_secret"] == "s3cret-from-a-file"
    assert oidc["scopes"] == ["openid", "profile", "groups"]
    assert oidc["group_mapping"] == [{"group": "eng", "space": "docs", "role": "editor"}]
    assert env.managed("oidc") == {
        "enabled",
        "issuer",
        "client_id",
        "client_secret",
        "scopes",
        "group_mapping",
    }
    assert env.values("ldap") == {
        "url": "ldap://ldap.example.com",
        "start_tls": True,
        # A DN contains commas: admin groups are JSON, never split on commas.
        "admin_groups": ["cn=wiki-admins,ou=groups,dc=example,dc=com"],
    }


@pytest.mark.parametrize(
    ("variables", "message"),
    [
        ({"BACKEND_OIDC_ISSUER": "http://idp.example.com"}, "BACKEND_OIDC_ISSUER"),
        ({"BACKEND_OIDC_ID_TOKEN_ALGORITHM": "none"}, "BACKEND_OIDC_ID_TOKEN_ALGORITHM"),
        ({"BACKEND_OIDC_ID_TOKEN_ALGORITHM": "HS256"}, "BACKEND_OIDC_ID_TOKEN_ALGORITHM"),
        ({"BACKEND_OIDC_CLIENT_SECRET": "plain"}, "use BACKEND_OIDC_CLIENT_SECRET_FILE"),
        ({"BACKEND_OIDC_CLIENT_SECRET_FILE": "/nonexistent"}, "cannot read"),
        ({"BACKEND_OIDC_ISUER": ISSUER}, "unknown variable"),
        ({"BACKEND_OIDC_SCOPES": "profile"}, "openid"),
        ({"BACKEND_OIDC_GROUP_MAPPING": "{not json"}, "not valid JSON"),
        (
            {"BACKEND_OIDC_GROUP_MAPPING": '[{"group": "g", "space": "Bad Key", "role": "x"}]'},
            "GROUP_MAPPING",
        ),
        ({"BACKEND_LDAP_URL": "ldap://ldap.example.com"}, "StartTLS"),
        ({"BACKEND_LDAP_URL": "https://ldap.example.com"}, "BACKEND_LDAP_URL"),
        ({"BACKEND_LDAP_USER_FILTER": "(uid=bob)"}, "{username}"),
        ({"BACKEND_LDAP_BIND_PASSWORD": "plain"}, "use BACKEND_LDAP_BIND_PASSWORD_FILE"),
    ],
)
def test_invalid_configuration_is_refused(variables: dict[str, str], message: str) -> None:
    with pytest.raises(
        SsoConfigurationError, match=message.replace("{", r"\{").replace("}", r"\}")
    ):
        load(variables)


def test_invalid_environment_fails_application_startup(
    monkeypatch: pytest.MonkeyPatch,
    settings: Settings,
    engine: Engine,
    secrets_provider: FileSecretsProvider,
) -> None:
    monkeypatch.setenv("BACKEND_OIDC_ISSUER", "http://idp.example.com")
    with pytest.raises(SsoConfigurationError, match="BACKEND_OIDC_ISSUER"):
        create_app(settings, engine=engine, secrets=secrets_provider)
