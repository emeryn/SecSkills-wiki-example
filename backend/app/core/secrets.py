"""Secrets provider abstraction. Secrets come from files, never from environment values."""

from pathlib import Path
from typing import Protocol

from app.core.config import Settings


class SecretsProvider(Protocol):
    """Source of secret material, addressed by a relative name such as ``db/runtime_password``."""

    def read(self, name: str) -> str:
        """Return the secret value, stripped of surrounding whitespace."""
        ...

    def file_path(self, name: str) -> Path:
        """Return a filesystem path to the secret, for libraries that only accept paths."""
        ...


class FileSecretsProvider:
    """Reads secrets from a directory (the volume populated by ``core.bootstrap``)."""

    def __init__(self, base_dir: Path) -> None:
        self._base_dir = base_dir.resolve()

    def file_path(self, name: str) -> Path:
        path = (self._base_dir / name).resolve()
        if not path.is_relative_to(self._base_dir):
            raise ValueError("Secret name escapes the secrets directory")
        return path

    def read(self, name: str) -> str:
        return self.file_path(name).read_text(encoding="utf-8").strip()


def build_secrets_provider(settings: Settings) -> SecretsProvider:
    """Return the provider selected by ``BACKEND_SECRETS_PROVIDER``."""
    return FileSecretsProvider(settings.secrets_dir)
