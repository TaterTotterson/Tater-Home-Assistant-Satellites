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


async def async_setup_entry(
    hass,
    entry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up satellite connection sensors."""
    manager: TaterSatelliteManager = entry.runtime_data
    manager.register_platform(
        "binary_sensor",
        lambda runtime: [TaterConnectionSensor(runtime)],
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
