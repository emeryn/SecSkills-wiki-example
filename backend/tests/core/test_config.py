import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_defaults_are_production_safe() -> None:
    settings = Settings()
    assert settings.environment == "production"
    assert settings.api_docs_enabled is False
    assert settings.sandbox_enabled is True


def test_invalid_environment_value_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BACKEND_TRUSTED_PROXY_COUNT", "99")
    with pytest.raises(ValidationError):
        Settings()


def test_unknown_secrets_provider_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BACKEND_SECRETS_PROVIDER", "plaintext-env")
    with pytest.raises(ValidationError):
        Settings()
