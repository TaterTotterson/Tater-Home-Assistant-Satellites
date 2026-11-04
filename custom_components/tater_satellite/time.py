"""Time entities for supported satellite display schedules."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time

from homeassistant.components.time import TimeEntity
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .entity import TaterSatelliteEntity
from .manager import SatelliteRuntime, TaterSatelliteManager
from .settings import supports_do_not_disturb, supports_screen_power_management


@dataclass(frozen=True, slots=True)
class TimeDefinition:
    """Describe a satellite display schedule time."""

    key: str
    name: str
    icon: str


DEFINITIONS = (
    TimeDefinition("screen_night_start", "Screen dim time", "mdi:weather-night"),
    TimeDefinition("screen_night_end", "Screen restore time", "mdi:weather-sunset-up"),
)
DND_DEFINITIONS = (
    TimeDefinition("dnd_start", "Do Not Disturb start", "mdi:bell-sleep"),
    TimeDefinition("dnd_end", "Do Not Disturb end", "mdi:bell-ring"),
)


async def async_setup_entry(
    hass,
    entry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up satellite display and Do Not Disturb schedule entities."""
    manager: TaterSatelliteManager = entry.runtime_data
    manager.register_platform(
        "time",
        lambda runtime: (
            [
                TaterSettingsTime(runtime, definition)
                for definition in DEFINITIONS
            ]
            if supports_screen_power_management(
                runtime.board, runtime.capabilities
            )
            else []
        )
        + (
            [
                TaterSettingsTime(runtime, definition)
                for definition in DND_DEFINITIONS
            ]
            if supports_do_not_disturb(runtime.capabilities)
            else []
        ),
        async_add_entities,
    )


class TaterSettingsTime(TaterSatelliteEntity, TimeEntity):
    """One local-time satellite display schedule setting."""

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
