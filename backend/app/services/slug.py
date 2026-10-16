"""Server-generated URL segments: ``[a-z0-9-]``, bounded length, never user-controlled paths."""

import re
import unicodedata
from collections.abc import Callable

_NOT_ALLOWED = re.compile(r"[^a-z0-9]+")


def slugify(text: str, max_length: int, fallback: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    slug = _NOT_ALLOWED.sub("-", ascii_text.lower()).strip("-")[:max_length].strip("-")
    return slug or fallback


def unique_slug(text: str, max_length: int, fallback: str, taken: Callable[[str], bool]) -> str:
    """First free candidate among ``slug``, ``slug-2``, ``slug-3``…"""
    base = slugify(text, max_length, fallback)
    candidate, counter = base, 1
    while taken(candidate):
        counter += 1
        suffix = f"-{counter}"
        candidate = base[: max_length - len(suffix)].rstrip("-") + suffix
    return candidate
