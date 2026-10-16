"""Encrypted personal data of users (email, display name) behind plain accessors."""

import uuid
from dataclasses import dataclass

from app.core.crypto import FieldCipher
from app.models import User

EMAIL_INDEX = "users.email"


@dataclass(frozen=True)
class Profile:
    email: str | None
    display_name: str | None


def new_user(cipher: FieldCipher, username: str, *, role: str = "user") -> User:
    """User with an id and a fresh data key, so encrypted fields can be bound to the record."""
    _, wrapped = cipher.new_data_key()
    return User(
        id=uuid.uuid4(),
        username=username.strip(),
        dek_wrapped=wrapped,
        key_version=cipher.key_version,
        global_role=role,
        status="active",
        auth_source="local",
        must_change_password=False,
    )


def set_profile(
    cipher: FieldCipher, user: User, *, email: str | None, display_name: str | None
) -> None:
    dek = cipher.unwrap(user.dek_wrapped)
    if email:
        user.email_enc = cipher.encrypt(dek, email.strip(), f"users.email:{user.id}")
        user.email_bidx = cipher.blind_index(email, EMAIL_INDEX)
    else:
        user.email_enc = None
        user.email_bidx = None
    user.display_name_enc = (
        cipher.encrypt(dek, display_name.strip(), f"users.display_name:{user.id}")
        if display_name
        else None
    )


def read_profile(cipher: FieldCipher, user: User) -> Profile:
    dek = cipher.unwrap(user.dek_wrapped)
    return Profile(
        email=cipher.decrypt(dek, user.email_enc, f"users.email:{user.id}")
        if user.email_enc
        else None,
        display_name=(
            cipher.decrypt(dek, user.display_name_enc, f"users.display_name:{user.id}")
            if user.display_name_enc
            else None
        ),
    )


def email_index(cipher: FieldCipher, email: str) -> bytes:
    return cipher.blind_index(email, EMAIL_INDEX)
