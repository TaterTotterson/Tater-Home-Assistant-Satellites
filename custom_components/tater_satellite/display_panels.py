"""Home Assistant climate and camera panels for Tater Echo screens."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.components.camera import async_get_image
from homeassistant.core import Event, EventStateChangedData, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_state_change_event

from .display_payloads import (
    MAX_ROOM_TEMPERATURES,
    camera_frame,
    cameras_payload,
    climate_payload,
    entity_hvac_mode,
    parse_entity_list,
    room_temperature_row,
    supports_display_cameras,
    supports_display_climate,
    unavailable_climate_payload,
)

if TYPE_CHECKING:
    from .manager import SatelliteRuntime, TaterSatelliteManager

_LOGGER = logging.getLogger(__name__)

CAMERA_FRAME_INTERVAL_SECONDS = 1.0
# Stop streaming if the screen never closes the camera view.
CAMERA_STREAM_MAX_SECONDS = 15 * 60
CAMERA_FRAME_WIDTH = 1280

DISPLAY_PANEL_MESSAGES = {
    "display.climate.action",
    "display.cameras.open",
    "display.camera.select",
    "display.camera.close",
}


def _text(value: Any) -> str:
    return str(value or "").strip()


class TaterDisplayPanelCoordinator:
    """Serve the screen's Climate and Cameras panels from Home Assistant."""

    def __init__(self, manager: TaterSatelliteManager) -> None:
        self.manager = manager
        self.hass = manager.hass
        self._climate_unsubs: dict[str, Any] = {}
        self._camera_tasks: dict[str, asyncio.Task[None]] = {}

    @staticmethod
    def climate_entity_id(runtime: SatelliteRuntime) -> str:
        """Return the thermostat assigned to this satellite, if any."""
        overrides = runtime.record.get("overrides")
        if isinstance(overrides, dict) and "screen_climate_entity" in overrides:
            return _text(overrides["screen_climate_entity"])
        # Assignments made before the setting existed.
        return _text(runtime.record.get("climate_entity_id"))

    @staticmethod
    def room_temperature_entity_ids(runtime: SatelliteRuntime) -> list[str]:
        """Return the temperature sensors chosen for the Climate panel."""
        overrides = runtime.record.get("overrides")
        value = (
            overrides.get("screen_room_temperature_entities")
            if isinstance(overrides, dict)
            else ""
        )
        return parse_entity_list(value, "sensor", MAX_ROOM_TEMPERATURES)

    def room_temperature_field_options(self) -> list[dict[str, str]]:
        """Return every temperature sensor, labelled by area and name."""
        rows = []
        for state in self.hass.states.async_all("sensor"):
            if state.attributes.get("device_class") != "temperature":
                continue
            area = self._area_name(state.entity_id)
            label = f"{area} · {state.name}" if area and area != state.name else state.name
            rows.append({"value": state.entity_id, "label": label})
        return sorted(rows, key=lambda row: row["label"].lower())

    def climate_field_options(self) -> list[dict[str, str]]:
        """Return the Thermostat field's dashboard options."""
        return [
            {"value": "", "label": "None"},
            *[
                {"value": entity_id, "label": label}
                for label, entity_id in self.climate_options()
            ],
        ]

    def climate_options(self) -> list[tuple[str, str]]:
        """Return (label, entity_id) for every thermostat, labelled by name."""
        states = sorted(
            self.hass.states.async_all("climate"), key=lambda row: row.name.lower()
        )
        names = [state.name for state in states]
        return [
            (
                state.name
                if names.count(state.name) == 1
                else f"{state.name} ({state.entity_id})",
                state.entity_id,
            )
            for state in states
        ]

    def _area_name(self, entity_id: str) -> str:
        entry = er.async_get(self.hass).async_get(entity_id)
        area_id = entry.area_id if entry is not None else None
        if not area_id and entry is not None and entry.device_id:
            device = dr.async_get(self.hass).async_get(entry.device_id)
            area_id = device.area_id if device is not None else None
        area = ar.async_get(self.hass).async_get_area(area_id) if area_id else None
        return area.name if area is not None else ""

    # Climate

    async def async_refresh_runtime(self, runtime: SatelliteRuntime) -> None:
        """Track the satellite's thermostat and push its current state."""
        self._track_climate(runtime)
        await self.async_push_climate(runtime)


    def _track_climate(self, runtime: SatelliteRuntime) -> None:
        unsub = self._climate_unsubs.pop(runtime.device_id, None)
        if unsub is not None:
            unsub()
        entity_ids = [
            entity_id
            for entity_id in (
                self.climate_entity_id(runtime),
                *self.room_temperature_entity_ids(runtime),
            )
            if entity_id
        ]
        if not entity_ids or not supports_display_climate(runtime.capabilities):
            return

        @callback
        def _changed(_event: Event[EventStateChangedData]) -> None:
            self.manager.entry.async_create_background_task(
                self.hass,
                self.async_push_climate(runtime),
                f"tater_satellite_climate_{runtime.device_id}",
            )

        self._climate_unsubs[runtime.device_id] = async_track_state_change_event(
            self.hass, entity_ids, _changed
        )

    async def async_push_climate(self, runtime: SatelliteRuntime) -> bool:
        """Send the thermostat state, or an unavailable panel, to the screen."""
        if not runtime.connected or not supports_display_climate(runtime.capabilities):
            return False
        entity_id = self.climate_entity_id(runtime)
        state = self.hass.states.get(entity_id) if entity_id else None
        if state is None:
            payload = unavailable_climate_payload()
        else:
            payload = climate_payload(
                entity_id,
                state.state,
                state.attributes,
                room_name=self._area_name(entity_id) or state.name,
                temperature_unit=self.hass.config.units.temperature_unit,
            )
        rooms = []
        for sensor_id in self.room_temperature_entity_ids(runtime):
            sensor = self.hass.states.get(sensor_id)
            if sensor is None:
                continue
            row = room_temperature_row(
                sensor_id,
                sensor.state,
                sensor.attributes,
                room_name=self._area_name(sensor_id) or sensor.name,
            )
            if row is not None:
                rooms.append(row)
        if rooms:
            payload["room_temperatures"] = rooms
        return await runtime.async_send("display.climate", payload)

    async def async_set_climate_entity(
        self, runtime: SatelliteRuntime, entity_id: str
    ) -> None:
        """Assign a thermostat to the satellite and refresh its screen."""
        entity_id = _text(entity_id)
        if entity_id and not entity_id.startswith("climate."):
            raise ValueError(f"{entity_id} is not a climate entity")
        # The settings save refreshes the panel through async_refresh_runtime.
        await self.manager.async_set_device_settings(
            runtime.device_id, {"screen_climate_entity": entity_id}
        )

    async def _async_climate_action(
        self, runtime: SatelliteRuntime, payload: dict[str, Any]
    ) -> None:
        entity_id = self.climate_entity_id(runtime)
        if not entity_id or _text(payload.get("room_id")) != entity_id:
            runtime.add_log("warning", "Ignored a climate action for an unassigned thermostat")
            return
        action = _text(payload.get("action"))
        try:
            if action == "set_temperature":
                await self.hass.services.async_call(
                    "climate",
                    "set_temperature",
                    {"entity_id": entity_id, "temperature": float(payload["value"])},
                    blocking=True,
                )
            elif action == "set_hvac_mode":
                state = self.hass.states.get(entity_id)
                modes = state.attributes.get("hvac_modes", []) if state else []
                mode = entity_hvac_mode(payload.get("mode"), modes)
                if not mode:
                    raise ValueError(f"{entity_id} does not support {payload.get('mode')}")
                await self.hass.services.async_call(
                    "climate",
                    "set_hvac_mode",
                    {"entity_id": entity_id, "hvac_mode": mode},
                    blocking=True,
                )
            else:
                return
        except (HomeAssistantError, KeyError, TypeError, ValueError) as err:
            runtime.add_log("error", f"Thermostat {action} failed: {err}")
            _LOGGER.warning("Thermostat %s on %s failed: %s", action, entity_id, err)
        # Re-send the real state so a rejected change does not linger on screen.
        await self.async_push_climate(runtime)

    # Cameras

    def _camera_rows(self) -> list[dict[str, Any]]:
        return [
            {
                "id": state.entity_id,
                "name": state.name,
                "room": self._area_name(state.entity_id),
                "available": state.state not in {"unavailable", "unknown"},
            }
            for state in sorted(
                self.hass.states.async_all("camera"), key=lambda row: row.name.lower()
            )
        ]

    async def _async_send_cameras(self, runtime: SatelliteRuntime, **kwargs: Any) -> None:
        await runtime.async_send("display.cameras", cameras_payload(self._camera_rows(), **kwargs))

    async def _async_stop_camera(self, device_id: str) -> None:
        task = self._camera_tasks.pop(device_id, None)
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def _async_stream_camera(self, runtime: SatelliteRuntime, entity_id: str) -> None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + CAMERA_STREAM_MAX_SECONDS
        loading = True
        while runtime.connected and loop.time() < deadline:
            started = loop.time()
            try:
                image = await async_get_image(
                    self.hass, entity_id, timeout=10, width=CAMERA_FRAME_WIDTH
                )
            except HomeAssistantError as err:
                await self._async_send_cameras(
                    runtime, selected_id=entity_id, error=f"Camera unavailable: {err}"
                )
                return
            frame = camera_frame(image.content)
            if frame is None:
                await self._async_send_cameras(
                    runtime,
                    selected_id=entity_id,
                    error=f"Camera returned an unsupported {image.content_type} image",
                )
                return
            if not await runtime.async_send_bytes(frame):
                return
            if loading:
                loading = False
                await self._async_send_cameras(runtime, selected_id=entity_id)
            await asyncio.sleep(
                max(0.0, CAMERA_FRAME_INTERVAL_SECONDS - (loop.time() - started))
            )

    async def _async_select_camera(self, runtime: SatelliteRuntime, entity_id: str) -> None:
        await self._async_stop_camera(runtime.device_id)
        if self.hass.states.get(entity_id) is None or not entity_id.startswith("camera."):
            await self._async_send_cameras(runtime, error="That camera is not available")
            return
        await self._async_send_cameras(runtime, selected_id=entity_id, loading=True)
        self._camera_tasks[runtime.device_id] = self.manager.entry.async_create_background_task(
            self.hass,
            self._async_stream_camera(runtime, entity_id),
            f"tater_satellite_camera_{runtime.device_id}",
        )

    # Routing and lifecycle

    async def async_handle_message(
        self, runtime: SatelliteRuntime, kind: str, payload: dict[str, Any]
    ) -> bool:
        """Handle a screen panel request; return False for other messages."""
        if kind not in DISPLAY_PANEL_MESSAGES:
            return False
        if kind == "display.climate.action":
            if supports_display_climate(runtime.capabilities):
                await self._async_climate_action(runtime, payload)
            return True
        if not supports_display_cameras(runtime.capabilities):
            return True
        if kind == "display.cameras.open":
            await self._async_send_cameras(runtime)
        elif kind == "display.camera.select":
            await self._async_select_camera(runtime, _text(payload.get("camera_id")))
        elif kind == "display.camera.close":
            await self._async_stop_camera(runtime.device_id)
        return True

    async def async_handle_disconnect(self, runtime: SatelliteRuntime) -> None:
        """Stop streams and state tracking for a disconnected satellite."""
        unsub = self._climate_unsubs.pop(runtime.device_id, None)
        if unsub is not None:
            unsub()
        await self._async_stop_camera(runtime.device_id)

    async def async_shutdown(self) -> None:
        """Stop every camera stream and state listener."""
        for unsub in self._climate_unsubs.values():
            unsub()
        self._climate_unsubs.clear()
        for device_id in tuple(self._camera_tasks):
            await self._async_stop_camera(device_id)
