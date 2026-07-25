"""Shared entity helpers for Tater satellites."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN
from .manager import SatelliteRuntime


class TaterSatelliteEntity(Entity):
    """Base entity backed by a satellite runtime."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, runtime: SatelliteRuntime, key: str) -> None:
        self.runtime = runtime
        self._attr_unique_id = f"{runtime.device_id}_{key}"
        runtime.manager.attach_entity(runtime, self)

    @property
    def available(self) -> bool:
        """Return whether the satellite is connected."""
        return self.runtime.connected

    @property
    def device_info(self) -> DeviceInfo:
        """Return device registry metadata."""
        return DeviceInfo(
            identifiers={(DOMAIN, self.runtime.device_id)},
            name=self.runtime.name,
            manufacturer="Tater",
            model=self.runtime.board or "Native Satellite",
            sw_version=self.runtime.firmware_version or None,
            suggested_area=self.runtime.room or None,
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return common satellite diagnostics."""
        return {
            "device_id": self.runtime.device_id,
            "board": self.runtime.board,
            "room": self.runtime.room,
            "firmware_version": self.runtime.firmware_version,
            "remote": self.runtime.remote,
        }
