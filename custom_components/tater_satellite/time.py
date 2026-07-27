"""Time entities for S3 Box display schedules."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time

from homeassistant.components.time import TimeEntity
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .entity import TaterSatelliteEntity
from .manager import SatelliteRuntime, TaterSatelliteManager
from .settings import board_supports_screen_settings


@dataclass(frozen=True, slots=True)
class TimeDefinition:
    """Describe an S3 Box display schedule time."""

    key: str
    name: str
    icon: str


DEFINITIONS = (
    TimeDefinition("screen_night_start", "Screen dim time", "mdi:weather-night"),
    TimeDefinition("screen_night_end", "Screen restore time", "mdi:weather-sunset-up"),
)


async def async_setup_entry(
    hass,
    entry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up S3 Box display schedule entities."""
    manager: TaterSatelliteManager = entry.runtime_data
    manager.register_platform(
        "time",
        lambda runtime: (
            [
                TaterSettingsTime(runtime, definition)
                for definition in DEFINITIONS
            ]
            if board_supports_screen_settings(runtime.board)
            else []
        ),
        async_add_entities,
    )


class TaterSettingsTime(TaterSatelliteEntity, TimeEntity):
    """One local-time S3 Box display schedule setting."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, runtime: SatelliteRuntime, definition: TimeDefinition) -> None:
        super().__init__(runtime, definition.key)
        self.definition = definition
        self._attr_name = definition.name
        self._attr_icon = definition.icon

    @property
    def native_value(self) -> time | None:
        """Return the configured local time."""
        value = str(
            self.runtime.effective_settings().get(self.definition.key) or ""
        )
        try:
            return time.fromisoformat(value)
        except ValueError:
            return None

    async def async_set_value(self, value: time) -> None:
        """Set the configured local time."""
        await self.runtime.manager.async_set_device_settings(
            self.runtime.device_id,
            {self.definition.key: value.strftime("%H:%M")},
        )
