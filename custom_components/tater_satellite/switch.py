"""Switch entities for Tater satellite settings."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .entity import TaterSatelliteEntity
from .manager import SatelliteRuntime, TaterSatelliteManager


@dataclass(frozen=True, slots=True)
class SwitchDefinition:
    """Describe a boolean firmware setting."""

    key: str
    name: str
    icon: str
    category: EntityCategory | None = EntityCategory.CONFIG


DEFINITIONS = (
    SwitchDefinition("muted", "Microphone mute", "mdi:microphone-off"),
    SwitchDefinition("continued_chat", "Continued conversation", "mdi:account-voice"),
    SwitchDefinition("barge_in_enabled", "Reply barge-in", "mdi:account-voice"),
    SwitchDefinition("wake_sound_enabled", "Wake sound", "mdi:music-note"),
    SwitchDefinition("aec_enabled", "Echo cancellation", "mdi:waveform"),
    SwitchDefinition(
        "capture_wake_audio", "Trainer good-wake capture", "mdi:record-rec"
    ),
    SwitchDefinition(
        "capture_close_misses", "Trainer close-miss capture", "mdi:record-circle"
    ),
)


async def async_setup_entry(
    hass,
    entry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Tater satellite switches."""
    manager: TaterSatelliteManager = entry.runtime_data
    manager.register_platform(
        "switch",
        lambda runtime: [
            TaterSettingsSwitch(runtime, definition) for definition in DEFINITIONS
        ],
        async_add_entities,
    )


class TaterSettingsSwitch(TaterSatelliteEntity, SwitchEntity):
    """A boolean live firmware setting."""

    def __init__(self, runtime: SatelliteRuntime, definition: SwitchDefinition) -> None:
        super().__init__(runtime, definition.key)
        self.definition = definition
        self._attr_name = definition.name
        self._attr_icon = definition.icon
        self._attr_entity_category = definition.category

    @property
    def is_on(self) -> bool:
        """Return the current resolved setting."""
        return bool(self.runtime.effective_settings().get(self.definition.key))

    async def async_turn_on(self, **kwargs) -> None:
        """Enable the setting."""
        await self.runtime.manager.async_set_device_settings(
            self.runtime.device_id, {self.definition.key: True}
        )

    async def async_turn_off(self, **kwargs) -> None:
        """Disable the setting."""
        await self.runtime.manager.async_set_device_settings(
            self.runtime.device_id, {self.definition.key: False}
        )
