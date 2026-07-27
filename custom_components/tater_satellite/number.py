"""Number entities for Tater satellite settings."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .entity import TaterSatelliteEntity
from .manager import SatelliteRuntime, TaterSatelliteManager
from .settings import board_supports_led_settings, board_supports_screen_settings


@dataclass(frozen=True, slots=True)
class NumberDefinition:
    """Describe a numeric firmware setting."""

    key: str
    name: str
    minimum: float
    maximum: float
    step: float
    unit: str | None
    icon: str


DEFINITIONS = (
    NumberDefinition(
        "screen_brightness",
        "Screen brightness",
        0,
        100,
        1,
        "%",
        "mdi:brightness-6",
    ),
    NumberDefinition(
        "screen_night_brightness",
        "Night screen brightness",
        0,
        100,
        1,
        "%",
        "mdi:brightness-4",
    ),
    NumberDefinition(
        "led_brightness", "LED brightness", 0, 100, 1, "%", "mdi:brightness-6"
    ),
    NumberDefinition(
        "wake_threshold",
        "Wake base threshold",
        0.01,
        0.99,
        0.01,
        None,
        "mdi:waveform",
    ),
    NumberDefinition(
        "wake_sliding_window",
        "Wake sliding window",
        1,
        10,
        1,
        None,
        "mdi:chart-bell-curve",
    ),
    NumberDefinition(
        "close_miss_threshold",
        "Close-miss threshold",
        0.01,
        0.99,
        0.01,
        None,
        "mdi:waveform",
    ),
    NumberDefinition(
        "aec_strength_percent",
        "Echo cancellation strength",
        0,
        100,
        1,
        "%",
        "mdi:waveform",
    ),
    NumberDefinition(
        "aec_delay_ms",
        "Echo cancellation delay",
        0,
        220,
        5,
        "ms",
        "mdi:timer-outline",
    ),
)


async def async_setup_entry(
    hass,
    entry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Tater satellite number entities."""
    manager: TaterSatelliteManager = entry.runtime_data
    manager.register_platform(
        "number",
        lambda runtime: [
            TaterSettingsNumber(runtime, definition)
            for definition in DEFINITIONS
            if (
                (
                    not definition.key.startswith("screen_")
                    or board_supports_screen_settings(runtime.board)
                )
                and (
                    definition.key != "led_brightness"
                    or board_supports_led_settings(runtime.board)
                )
            )
        ],
        async_add_entities,
    )


class TaterSettingsNumber(TaterSatelliteEntity, NumberEntity):
    """A numeric live firmware setting."""

    _attr_mode = NumberMode.SLIDER
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, runtime: SatelliteRuntime, definition: NumberDefinition) -> None:
        super().__init__(runtime, definition.key)
        self.definition = definition
        self._attr_name = definition.name
        self._attr_icon = definition.icon
        self._attr_native_min_value = definition.minimum
        self._attr_native_max_value = definition.maximum
        self._attr_native_step = definition.step
        self._attr_native_unit_of_measurement = definition.unit

    @property
    def native_value(self) -> float:
        """Return the current resolved value."""
        return float(self.runtime.effective_settings().get(self.definition.key) or 0)

    async def async_set_native_value(self, value: float) -> None:
        """Set the numeric firmware value."""
        await self.runtime.manager.async_set_device_settings(
            self.runtime.device_id, {self.definition.key: value}
        )
