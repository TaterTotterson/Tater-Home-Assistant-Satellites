"""Helpers for the Tater native satellite wire protocol."""

from __future__ import annotations

import json
import struct
import time
import uuid
from typing import Any

from .const import PROTOCOL_VERSION

WAKE_VERIFY_MAGIC = b"TWV1"
WAKE_VERIFY_HEADER = struct.Struct("<4sBBHIII")


def text(value: Any) -> str:
    """Return a stripped string."""
    return str(value or "").strip()


def envelope(
    message_type: str,
    payload: dict[str, Any] | None = None,
    *,
    message_id: str = "",
) -> dict[str, Any]:
    """Create a versioned protocol envelope."""
    return {
        "v": PROTOCOL_VERSION,
        "type": text(message_type),
        "id": message_id or uuid.uuid4().hex,
        "ts": time.time(),
        "payload": payload or {},
    }


def parse_text_message(raw: str | bytes) -> dict[str, Any]:
    """Parse and validate a JSON text message."""
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError(  # noqa: TRY004
            "Satellite message must be a JSON object"
        )
    if not text(value.get("type")):
        raise ValueError("Satellite message is missing its type")
    payload = value.get("payload")
    if payload is not None and not isinstance(payload, dict):
        raise ValueError("Satellite message payload must be an object")
    return value


def message_type(message: dict[str, Any]) -> str:
    """Return the normalized message type."""
    return text(message.get("type")).lower()


def message_payload(message: dict[str, Any]) -> dict[str, Any]:
    """Return the message payload."""
    payload = message.get("payload")
    return payload if isinstance(payload, dict) else {}


def is_wake_verifier_packet(data: bytes) -> bool:
    """Return whether a binary frame is a Tater wake-verifier packet."""
    return len(data) >= WAKE_VERIFY_HEADER.size and data[:4] == WAKE_VERIFY_MAGIC


def wake_verifier_request_id(data: bytes) -> int:
    """Extract a request id from a wake-verifier packet."""
    if not is_wake_verifier_packet(data):
        return 0
    _magic, _version, _codec, _flags, request_id, _rate, _samples = (
        WAKE_VERIFY_HEADER.unpack_from(data)
    )
    return int(request_id)


def wake_verifier_unavailable(data: bytes) -> dict[str, Any]:
    """Build a fail-open result when no verifier service is configured."""
    return envelope(
        "wake.verify.result",
        {
            "request_id": wake_verifier_request_id(data),
            "accepted": True,
            "available": False,
            "reason": "home_assistant_verifier_unavailable_fail_open",
        },
    )
