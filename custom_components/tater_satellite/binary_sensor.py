"""Binary sensors for Tater satellites."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .entity import TaterSatelliteEntity
from .manager import SatelliteRuntime, TaterSatelliteManager
from .settings import supports_do_not_disturb


async def async_setup_entry(
    hass,
    entry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up satellite connection and Do Not Disturb sensors."""
    manager: TaterSatelliteManager = entry.runtime_data
    manager.register_platform(
        "binary_sensor",
        lambda runtime: [TaterConnectionSensor(runtime)]
        + (
            [TaterDndActiveSensor(runtime)]
            if supports_do_not_disturb(runtime.capabilities)
            else []
        ),
        async_add_entities,
    )


class TaterConnectionSensor(TaterSatelliteEntity, BinarySensorEntity):
    """Satellite connection status."""

    _attr_name = "Connection"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, runtime: SatelliteRuntime) -> None:
        super().__init__(runtime, "connection")

    @property
    def available(self) -> bool:
        """Connection status remains available while the device is offline."""
        return True

    @property
    def is_on(self) -> bool:
        """Return connection status."""
        return self.runtime.connected


class TaterDndActiveSensor(TaterSatelliteEntity, BinarySensorEntity):
    """Whether the satellite is enforcing Do Not Disturb right now.

    On while the manual switch is on or the daily window is open, as the
    firmware reports it in each status message.
    """

    _attr_name = "Do Not Disturb active"
    _attr_icon = "mdi:minus-circle"

    def __init__(self, runtime: SatelliteRuntime) -> None:
        super().__init__(runtime, "dnd_active")

    @property
    def is_on(self) -> bool | None:
        """Return the firmware's reported DND state."""
        value = self.runtime.last_status.get("dnd_active")
        return value if isinstance(value, bool) else None
