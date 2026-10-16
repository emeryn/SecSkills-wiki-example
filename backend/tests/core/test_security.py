from app.core.security import PasswordHasher
from app.services.password_policy import password_problems


def test_production_argon2id_parameters_meet_minimums() -> None:
    parameters = PasswordHasher("rfc9106").parameters
    assert parameters.type.name == "ID"
    assert parameters.memory_cost >= 19 * 1024
    assert parameters.time_cost >= 2


def test_verify_without_hash_never_succeeds() -> None:
    hasher = PasswordHasher("test")
    assert hasher.verify(None, "anything at all") is False
    stored = hasher.hash("a fine passphrase")
    assert hasher.verify(stored, "a fine passphrase") is True
    assert hasher.verify(stored, "another passphrase") is False


def test_password_policy() -> None:
    assert password_problems("short") == ["TOO_SHORT"]
    assert "COMMON_PASSWORD" in password_problems("password1234")
    assert "CONTAINS_USERNAME" in password_problems("bob is my long password", "bob")
    assert password_problems("x" * 129) == ["TOO_LONG"]
    assert password_problems("Tr0ub4dor & horse staple") == []
    # Spaces and any Unicode are allowed; no composition rules.
    assert password_problems("été à la plage, enfin") == []
