"""Password policy per NIST SP 800-63B: length only, no composition rules, common list rejected."""

import gzip
from functools import lru_cache
from pathlib import Path

from app.core.crypto import normalize

MIN_LENGTH = 12
MAX_LENGTH = 128
# Passwords of 12+ characters from the SecLists "Pwdb top 1,000,000" list (MIT licence).
COMMON_PASSWORDS_FILE = Path(__file__).resolve().parents[2] / "data" / "common-passwords.txt.gz"


@lru_cache(maxsize=1)
def _common_passwords() -> frozenset[str]:
    with gzip.open(COMMON_PASSWORDS_FILE, "rt", encoding="utf-8") as lines:
        return frozenset(line.rstrip("\n") for line in lines)


def password_problems(password: str, username: str | None = None) -> list[str]:
    """Return machine-readable reasons the password is refused; empty when acceptable."""
    problems: list[str] = []
    length = len(password)
    if length < MIN_LENGTH:
        problems.append("TOO_SHORT")
    if length > MAX_LENGTH:
        problems.append("TOO_LONG")
    canonical = normalize(password)
    if canonical in _common_passwords():
        problems.append("COMMON_PASSWORD")
    if username and normalize(username) in canonical:
        problems.append("CONTAINS_USERNAME")
    return problems
