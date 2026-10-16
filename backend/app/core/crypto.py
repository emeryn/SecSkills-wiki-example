"""Column-level encryption: AES-256-GCM envelope encryption and HMAC-SHA256 blind indexes.

Each record has its own data key (DEK), stored wrapped by the master key. The master key comes
from the secrets provider and is never stored in the database or its backups.
"""

import base64
import hashlib
import hmac
import secrets
import unicodedata

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

NONCE_BYTES = 12
KEY_BYTES = 32
CURRENT_KEY_VERSION = 1


def decode_key(encoded: str) -> bytes:
    """Decode a base64url key as written by the bootstrap (no padding)."""
    key = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
    if len(key) != KEY_BYTES:
        raise ValueError("Keys must be 32 bytes")
    return key


def _derive(master_key: bytes, purpose: str) -> bytes:
    return HKDF(
        algorithm=hashes.SHA256(), length=KEY_BYTES, salt=None, info=purpose.encode()
    ).derive(master_key)


def normalize(value: str) -> str:
    """Canonical form used before indexing: NFKC, case-folded, trimmed."""
    return unicodedata.normalize("NFKC", value).casefold().strip()


class FieldCipher:
    """Encrypts individual column values under per-record data keys."""

    def __init__(self, master_key: bytes, key_version: int = CURRENT_KEY_VERSION) -> None:
        self._kek = AESGCM(_derive(master_key, "wiki:kek"))
        self._index_key = _derive(master_key, "wiki:blind-index")
        self.key_version = key_version

    def new_data_key(self) -> tuple[bytes, bytes]:
        """Return ``(dek, wrapped_dek)``."""
        dek = AESGCM.generate_key(bit_length=256)
        nonce = secrets.token_bytes(NONCE_BYTES)
        return dek, nonce + self._kek.encrypt(nonce, dek, b"dek")

    def unwrap(self, wrapped: bytes) -> bytes:
        return self._kek.decrypt(wrapped[:NONCE_BYTES], wrapped[NONCE_BYTES:], b"dek")

    @staticmethod
    def encrypt(dek: bytes, plaintext: str, context: str) -> bytes:
        """Encrypt ``plaintext``; ``context`` (table.column:id) binds the value to its slot."""
        nonce = secrets.token_bytes(NONCE_BYTES)
        return nonce + AESGCM(dek).encrypt(nonce, plaintext.encode(), context.encode())

    @staticmethod
    def decrypt(dek: bytes, blob: bytes, context: str) -> str:
        return (
            AESGCM(dek).decrypt(blob[:NONCE_BYTES], blob[NONCE_BYTES:], context.encode()).decode()
        )

    def blind_index(self, value: str, purpose: str) -> bytes:
        """Deterministic keyed hash for equality lookups and uniqueness on encrypted columns."""
        message = f"{purpose}\x00{normalize(value)}".encode()
        return hmac.new(self._index_key, message, hashlib.sha256).digest()
