"""Names and rooms shared with satellite firmware."""

from typing import Any


def identity_text(value: Any, *, required: bool) -> str:
    """Validate the common Native/Echo/Linux firmware wire limits."""
    if not isinstance(value, str) or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError("Name and room must be text without control characters")
    value = value.strip(" ")
    if (required and not value) or len(value.encode("utf-8")) > 63:
        raise ValueError("Name must be 1–63 bytes and room at most 63 bytes")
    return value
