"""Diagnostic sensors for Tater satellites."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, UnitOfInformation, UnitOfTime
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .entity import TaterSatelliteEntity
from .manager import SatelliteRuntime, TaterSatelliteManager


@dataclass(frozen=True, slots=True)
class SensorDefinition:
    """Describe a status payload sensor."""

    key: str
    name: str
    icon: str
    unit: str | None = None
    device_class: SensorDeviceClass | None = None
    state_class: SensorStateClass | None = None


DEFINITIONS = (
    SensorDefinition(
        "wifi_rssi",
        "Wi-Fi signal",
        "mdi:wifi",
        "dBm",
        SensorDeviceClass.SIGNAL_STRENGTH,
        SensorStateClass.MEASUREMENT,
    ),
    SensorDefinition(
        "free_heap",
        "Free memory",
        "mdi:memory",
        UnitOfInformation.BYTES,
        SensorDeviceClass.DATA_SIZE,
        SensorStateClass.MEASUREMENT,
    ),
    SensorDefinition(
        "uptime_s",
        "Uptime",
        "mdi:clock-outline",
        UnitOfTime.SECONDS,
        SensorDeviceClass.DURATION,
        SensorStateClass.MEASUREMENT,
    ),
    SensorDefinition(
        "ota_progress",
        "OTA progress",
        "mdi:update",
        PERCENTAGE,
        None,
        SensorStateClass.MEASUREMENT,
    ),
)


async def async_setup_entry(
    hass,
    entry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up satellite diagnostics."""
    manager: TaterSatelliteManager = entry.runtime_data
    manager.register_platform(
        "sensor",
        lambda runtime: [
            TaterDiagnosticSensor(runtime, definition) for definition in DEFINITIONS
        ],
        async_add_entities,
    )


class TaterDiagnosticSensor(TaterSatelliteEntity, SensorEntity):
    """A value reported by satellite status frames."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, runtime: SatelliteRuntime, definition: SensorDefinition) -> None:
        super().__init__(runtime, definition.key)
        self.definition = definition
        self._attr_name = definition.name
        self._attr_icon = definition.icon
        self._attr_native_unit_of_measurement = definition.unit
        self._attr_device_class = definition.device_class
        self._attr_state_class = definition.state_class

    @property
    def native_value(self) -> Any:
        """Return the latest reported value."""
        if self.definition.key == "ota_progress":
            return self.runtime.ota_progress
        return self.runtime.last_status.get(self.definition.key)
