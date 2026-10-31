"""Climate and camera payloads for Tater Echo screen satellites."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

# Echo firmware prefixes each binary camera frame with this marker and rejects
# frames whose JPEG exceeds 4 MiB.
CAMERA_FRAME_PREFIX = b"TCAM1"
MAX_CAMERA_FRAME_BYTES = 4 * 1024 * 1024

# Home Assistant ClimateEntityFeature.TARGET_TEMPERATURE.
_TARGET_TEMPERATURE_FEATURE = 1

# The screen offers exactly these mode buttons.
SCREEN_HVAC_MODES = ("heat", "cool", "auto", "off")

_UNAVAILABLE_STATES = {"unavailable", "unknown", ""}


def supports_display_climate(capabilities: Mapping[str, Any] | None) -> bool:
    """Return whether firmware renders a pushed climate panel."""
    return isinstance(capabilities, Mapping) and bool(
        capabilities.get("screen_climate")
    )


def supports_display_cameras(capabilities: Mapping[str, Any] | None) -> bool:
    """Return whether firmware renders the camera panel."""
    return isinstance(capabilities, Mapping) and bool(
        capabilities.get("screen_cameras")
    )


def temperature_unit_letter(unit: str) -> str:
    """Return the firmware's single-letter unit for a Home Assistant unit."""
    return "C" if "C" in str(unit or "").upper() else "F"


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def screen_hvac_mode(mode: Any, entity_modes: Iterable[Any] = ()) -> str:
    """Map a Home Assistant HVAC mode to the screen's vocabulary."""
    token = str(mode or "").strip().lower()
    if token == "heat_cool" and "auto" not in {
        str(row).strip().lower() for row in entity_modes
    }:
        return "auto"
    return token


def entity_hvac_mode(screen_mode: Any, entity_modes: Iterable[Any]) -> str:
    """Map a screen mode button back to a mode the entity accepts, or ""."""
    token = str(screen_mode or "").strip().lower()
    modes = [str(row).strip().lower() for row in entity_modes]
    if token in modes:
        return token
    if token == "auto" and "heat_cool" in modes:
        return "heat_cool"
    return ""


# The Crown's Climate panel has room for six readings.
MAX_ROOM_TEMPERATURES = 6


def parse_entity_list(value: Any, domain: str, limit: int) -> list[str]:
    """Split a comma-separated setting into unique entity ids of one domain."""
    entity_ids: list[str] = []
    for item in str(value or "").split(","):
        entity_id = item.strip()
        if entity_id.startswith(f"{domain}.") and entity_id not in entity_ids:
            entity_ids.append(entity_id)
    return entity_ids[:limit]


def room_temperature_row(
    entity_id: str,
    state: str,
    attributes: Mapping[str, Any],
    *,
    room_name: str,
) -> dict[str, Any] | None:
    """Build one room_temperatures row, or None if there is no reading."""
    temperature = _number(state)
    if temperature is None:
        return None
    return {
        "room_id": entity_id,
        "room_name": room_name,
        "temperature": temperature,
        "temperature_unit": temperature_unit_letter(
            str(attributes.get("unit_of_measurement") or "")
        ),
    }


def unavailable_climate_payload() -> dict[str, Any]:
    """Return a payload that tells the screen no thermostat is configured."""
    return {"available": False}


def climate_payload(
    entity_id: str,
    state: str,
    attributes: Mapping[str, Any],
    *,
    room_name: str,
    temperature_unit: str,
) -> dict[str, Any]:
    """Build a display.climate payload from a climate entity's state."""
    if str(state or "").strip().lower() in _UNAVAILABLE_STATES:
        return {**unavailable_climate_payload(), "room_id": entity_id}
    entity_modes = list(attributes.get("hvac_modes") or [])
    screen_modes: list[str] = []
    for mode in entity_modes:
        mapped = screen_hvac_mode(mode, entity_modes)
        if mapped in SCREEN_HVAC_MODES and mapped not in screen_modes:
            screen_modes.append(mapped)
    features = int(_number(attributes.get("supported_features")) or 0)
    target = _number(attributes.get("temperature"))
    payload: dict[str, Any] = {
        "available": True,
        "room_id": entity_id,
        "room_name": room_name,
        "temperature_unit": temperature_unit_letter(temperature_unit),
        "hvac_mode": screen_hvac_mode(state, entity_modes),
        "hvac_action": str(attributes.get("hvac_action") or ""),
        "available_hvac_modes": screen_modes,
        "can_set_temperature": bool(features & _TARGET_TEMPERATURE_FEATURE)
        and target is not None,
        "can_set_mode": len(screen_modes) > 1,
    }
    for key, attribute in (
        ("current_temperature", "current_temperature"),
        ("target_temperature", "temperature"),
        ("current_humidity", "current_humidity"),
        ("minimum_temperature", "min_temp"),
        ("maximum_temperature", "max_temp"),
        ("temperature_step", "target_temp_step"),
    ):
        value = _number(attributes.get(attribute))
        if value is not None:
            payload[key] = value
    return payload


def cameras_payload(
    cameras: Iterable[Mapping[str, Any]],
    *,
    selected_id: str = "",
    loading: bool = False,
    error: str = "",
) -> dict[str, Any]:
    """Build a display.cameras payload.

    Each camera row needs "id", "name", "room", and "available". Doorbell
    talkback is not offered, because Home Assistant has no generic API for it.
    """
    rows = [
        {
            "id": str(row["id"]),
            "name": str(row.get("name") or row["id"]),
            "room": str(row.get("room") or ""),
            "doorbell": False,
            "talkback": False,
            "available": bool(row.get("available")),
        }
        for row in cameras
        if row.get("id")
    ]
    payload: dict[str, Any] = {
        "available": bool(rows),
        "cameras": rows,
        "loading": loading,
    }
    selected = next((row for row in rows if row["id"] == selected_id), None)
    if selected is not None:
        payload.update(
            {
                "selected_id": selected["id"],
                "selected_name": selected["name"],
                "selected_room": selected["room"],
                "selected_talkback": False,
            }
        )
    if error:
        payload["error"] = error
    return payload


def camera_frame(jpeg: bytes) -> bytes | None:
    """Wrap a JPEG for the screen, or return None if firmware would reject it."""
    if len(jpeg) < 4 or jpeg[:2] != b"\xff\xd8" or len(jpeg) > MAX_CAMERA_FRAME_BYTES:
        return None
    return CAMERA_FRAME_PREFIX + jpeg
