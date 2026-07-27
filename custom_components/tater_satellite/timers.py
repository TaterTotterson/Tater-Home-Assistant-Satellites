"""Translate Home Assistant timer events to native satellite commands."""

from __future__ import annotations

from typing import Any


def _event_name(value: Any) -> str:
    token = getattr(value, "value", value)
    return str(token or "").strip().lower()


def _positive_int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def timer_event_command(
    event_type: Any,
    timer: Any,
) -> tuple[str, dict[str, Any]] | None:
    """Return the native command for one Home Assistant timer event.

    Home Assistant keeps a transient intent-side mirror so its built-in timer
    sentences can find and modify timers. The satellite owns the real countdown
    and rings locally, so a Home Assistant FINISHED event must not force a
    second alarm.
    """
    event = _event_name(event_type)
    timer_id = str(getattr(timer, "id", "") or "").strip()
    if not timer_id:
        return None

    if event == "finished":
        return None

    if event == "cancelled":
        return "timer.clear", {"id": timer_id, "source": "home_assistant"}

    if event != "started" and event != "updated":
        return None

    if not bool(getattr(timer, "is_active", False)):
        return "timer.clear", {"id": timer_id, "source": "home_assistant"}

    remaining_seconds = _positive_int(getattr(timer, "seconds_left", 0))
    original_seconds = _positive_int(getattr(timer, "created_seconds", 0))
    if remaining_seconds <= 0:
        return None
    if original_seconds <= 0:
        original_seconds = remaining_seconds

    payload = {
        "id": timer_id,
        "name": str(getattr(timer, "name", "") or "")[:63],
        "label": str(getattr(timer, "name", "") or "")[:63],
        "duration_ms": remaining_seconds * 1000,
        "remaining_ms": remaining_seconds * 1000,
        "original_duration_ms": original_seconds * 1000,
        "source": "home_assistant",
    }
    # timer.arm is also understood by the previous firmware generation, and
    # 0.2.8 treats it as an idempotent start/update for this exact timer id.
    return "timer.arm", payload
