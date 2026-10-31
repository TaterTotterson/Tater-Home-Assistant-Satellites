"""Wall-clock payloads for Tater Echo screen satellites."""

from __future__ import annotations

from datetime import datetime, tzinfo
from typing import Any

# Echo screens expect the controller to refresh its clock once a minute. The
# refresh also carries the current UTC offset across daylight-saving changes.
DISPLAY_CLOCK_INTERVAL_SECONDS = 60


def supports_display_clock(capabilities: dict[str, Any] | None) -> bool:
    """Return whether firmware accepts display.weather clock updates."""
    return isinstance(capabilities, dict) and bool(
        capabilities.get("screen_weather")
    )


def display_clock_payload(
    now: datetime,
    time_zone: tzinfo,
    zone_name: str,
) -> dict[str, Any]:
    """Build a display.weather payload that only sets the screen clock.

    Echo firmware keeps its system clock in UTC and adds utc_offset_seconds
    from this message. Weather stays unavailable because Home Assistant does
    not publish a weather card to the screen.
    """
    offset = now.astimezone(time_zone).utcoffset()
    return {
        "available": False,
        "clock_unix_ms": int(now.timestamp() * 1000),
        "utc_offset_seconds": int(offset.total_seconds()) if offset else 0,
        "timezone": zone_name,
    }
