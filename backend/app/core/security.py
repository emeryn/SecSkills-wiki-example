"""Password hashing (Argon2id) and opaque token helpers."""

import hashlib
import hmac
import secrets

import argon2
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

TOKEN_BYTES = 32


class PasswordHasher:
    """Argon2id with RFC 9106 parameters; hashes are rehashed on login when parameters change."""

    def __init__(self, profile: str = "rfc9106") -> None:
        if profile == "test":
            self._hasher = argon2.PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1)
        else:
            # RFC 9106 second recommended option: t=3, m=64 MiB, p=4 (above the 19 MiB minimum).
            self._hasher = argon2.PasswordHasher.from_parameters(
                argon2.profiles.RFC_9106_LOW_MEMORY
            )
        self._dummy_hash = self._hasher.hash(secrets.token_urlsafe(16))

    @property
    def parameters(self) -> argon2.Parameters:
        return argon2.extract_parameters(self._dummy_hash)

    def hash(self, password: str) -> str:
        return self._hasher.hash(password)

    def verify(self, password_hash: str | None, password: str) -> bool:
        """Constant-work check: an absent hash is verified against a dummy hash."""
        try:
            return self._hasher.verify(password_hash or self._dummy_hash, password) and (
                password_hash is not None
            )
        except VerifyMismatchError, VerificationError, InvalidHashError:
            return False

    def needs_rehash(self, password_hash: str) -> bool:
        return self._hasher.check_needs_rehash(password_hash)


def new_token() -> str:
    """Random URL-safe token with 256 bits of entropy."""
    return secrets.token_urlsafe(TOKEN_BYTES)


def token_hash(token: str) -> bytes:
    """Tokens are stored hashed; SHA-256 suffices for 256-bit random values."""
    return hashlib.sha256(token.encode()).digest()


def csrf_token(csrf_key: bytes, session_token_hash: bytes) -> str:
    """CSRF token bound to the session: HMAC of the session token hash."""
    return hmac.new(csrf_key, session_token_hash, hashlib.sha256).hexdigest()
