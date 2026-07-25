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
WAKE_VERIFY_VERSION = 1
WAKE_VERIFY_CODEC_PCM16_LE = 1
WAKE_VERIFY_SAMPLE_RATE = 16000
WAKE_VERIFY_MAX_SAMPLES = WAKE_VERIFY_SAMPLE_RATE * 2


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


def parse_wake_verifier_packet(data: bytes) -> dict[str, Any]:
    """Validate and unpack a Tater PCM16 wake-verifier packet."""
    raw = bytes(data or b"")
    if len(raw) < WAKE_VERIFY_HEADER.size:
        raise ValueError("Wake verifier packet is shorter than its header")
    magic, version, codec, flags, request_id, sample_rate, sample_count = (
        WAKE_VERIFY_HEADER.unpack_from(raw)
    )
    if magic != WAKE_VERIFY_MAGIC:
        raise ValueError("Wake verifier packet magic does not match")
    if version != WAKE_VERIFY_VERSION:
        raise ValueError(f"Unsupported wake verifier packet version: {version}")
    if codec != WAKE_VERIFY_CODEC_PCM16_LE:
        raise ValueError(f"Unsupported wake verifier codec: {codec}")
    if sample_rate != WAKE_VERIFY_SAMPLE_RATE:
        raise ValueError(f"Unsupported wake verifier sample rate: {sample_rate}")
    if sample_count < 1 or sample_count > WAKE_VERIFY_MAX_SAMPLES:
        raise ValueError(f"Invalid wake verifier sample count: {sample_count}")
    expected_size = WAKE_VERIFY_HEADER.size + (sample_count * 2)
    if len(raw) != expected_size:
        raise ValueError(
            f"Wake verifier packet size mismatch: expected {expected_size}, "
            f"received {len(raw)}"
        )
    return {
        "request_id": int(request_id),
        "sample_rate": int(sample_rate),
        "sample_count": int(sample_count),
        "enforce": bool(flags & 0x01),
        "pcm": raw[WAKE_VERIFY_HEADER.size :],
    }
