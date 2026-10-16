import secrets

import pytest
from cryptography.exceptions import InvalidTag

from app.core.crypto import FieldCipher


@pytest.fixture
def cipher() -> FieldCipher:
    return FieldCipher(secrets.token_bytes(32))


def test_round_trip_with_per_record_key(cipher: FieldCipher) -> None:
    dek, wrapped = cipher.new_data_key()
    assert cipher.unwrap(wrapped) == dek
    blob = cipher.encrypt(dek, "alice@example.com", "users.email:1")
    assert b"alice" not in blob
    assert cipher.decrypt(dek, blob, "users.email:1") == "alice@example.com"


def test_value_cannot_be_moved_to_another_record(cipher: FieldCipher) -> None:
    dek, _ = cipher.new_data_key()
    blob = cipher.encrypt(dek, "alice@example.com", "users.email:1")
    with pytest.raises(InvalidTag):
        cipher.decrypt(dek, blob, "users.email:2")


def test_other_master_key_cannot_unwrap(cipher: FieldCipher) -> None:
    _, wrapped = cipher.new_data_key()
    with pytest.raises(InvalidTag):
        FieldCipher(secrets.token_bytes(32)).unwrap(wrapped)


def test_blind_index_is_deterministic_normalized_and_keyed(cipher: FieldCipher) -> None:
    assert cipher.blind_index("Alice@Example.com ", "email") == cipher.blind_index(
        "alice@example.com", "email"
    )
    assert cipher.blind_index("alice@example.com", "email") != cipher.blind_index(
        "alice@example.com", "other"
    )
    other = FieldCipher(secrets.token_bytes(32))
    assert other.blind_index("alice@example.com", "email") != cipher.blind_index(
        "alice@example.com", "email"
    )
