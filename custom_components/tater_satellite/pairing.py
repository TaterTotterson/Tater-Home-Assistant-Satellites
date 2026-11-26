"""Retry policy for the first native satellite credential handoff."""

from __future__ import annotations

from collections import OrderedDict
import hashlib
import hmac
from typing import Any

PAIRING_RETRY_GRACE_SECONDS = 30.0
AUTH_FAILURE_IDLE_SECONDS = 30 * 60
AUTH_FAILURE_MAX_ENTRIES = 512


def rejected_credential_key(credential: str) -> bytes:
    """Fingerprint a rejected credential, treating formatted pairing codes equally."""
    compact = "".join(credential.split()).replace("-", "")
    if len(compact) == 6 and compact.isascii() and compact.isdigit():
        credential = compact
    return hashlib.sha256(credential.encode("utf-8")).digest()


class AuthFailureTracker:
    """Recognize unchanged retries without storing credentials or growing unbounded."""

    def __init__(
        self,
        *,
        max_entries: int = AUTH_FAILURE_MAX_ENTRIES,
        idle_seconds: float = AUTH_FAILURE_IDLE_SECONDS,
    ) -> None:
        if max_entries < 1 or idle_seconds <= 0:
            raise ValueError("Authentication retry limits must be positive")
        self._max_entries = max_entries
        self._idle_seconds = idle_seconds
        self._seen: OrderedDict[tuple[str, bytes], float] = OrderedDict()

    def is_new_failure(self, source: str, credential_key: bytes, *, now: float) -> bool:
        """Count once per source/credential while automatic retries keep arriving."""
        while self._seen and now - next(iter(self._seen.values())) >= self._idle_seconds:
            self._seen.popitem(last=False)
        key = (source, credential_key)
        is_new = key not in self._seen
        self._seen[key] = now
        self._seen.move_to_end(key)
        if len(self._seen) > self._max_entries:
            self._seen.popitem(last=False)
        return is_new


def normalize_pairing_code(value: Any) -> str:
    """Return the ASCII digits accepted by satellite setup and constant-time checks."""
    return "".join(ch for ch in str(value or "") if ch in "0123456789")


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
