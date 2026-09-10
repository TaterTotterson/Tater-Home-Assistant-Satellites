"""Retry policy for the first native satellite credential handoff."""

from __future__ import annotations

import hmac
from typing import Any


PAIRING_RETRY_GRACE_SECONDS = 30.0


def normalize_pairing_code(value: Any) -> str:
    """Return only the decimal characters accepted by satellite setup."""
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def normalize_hardware_id(value: Any) -> str:
    """Normalize a hardware identifier for an exact retry comparison."""
    return "".join(ch for ch in str(value or "").lower() if ch.isalnum())


def pairing_retry_token(
    *,
    supplied_code: Any,
    pairing_code: str,
    claimed_device_id: str,
    claimed_hardware_id: str,
    device_token: str,
    retry_expires_at: float,
    device_id: str,
    hardware_id: Any,
    now: float,
) -> str:
    """Return the pending token only to the device that first claimed it."""
    if not device_token or now >= retry_expires_at:
        return ""
    if not hmac.compare_digest(normalize_pairing_code(supplied_code), pairing_code):
        return ""
    if device_id != claimed_device_id:
        return ""
    expected_hardware_id = normalize_hardware_id(claimed_hardware_id)
    if expected_hardware_id and normalize_hardware_id(hardware_id) != expected_hardware_id:
        return ""
    return device_token
