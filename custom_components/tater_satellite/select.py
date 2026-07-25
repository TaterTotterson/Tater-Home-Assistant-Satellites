"""Select entities for Tater satellites."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.select import SelectEntity
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .entity import TaterSatelliteEntity
from .manager import SatelliteRuntime, TaterSatelliteManager
from .settings import (
    ANIMATION_OPTIONS,
    WAKE_SOUND_OPTIONS,
    board_supports_led_settings,
)

PREFERRED_PIPELINE = "preferred"


@dataclass(frozen=True, slots=True)
class SelectDefinition:
    """Describe a select firmware setting."""

    key: str
    name: str
    options: tuple[str, ...]
    icon: str


_ANIMATIONS = tuple(str(row["value"]) for row in ANIMATION_OPTIONS)
DEFINITIONS = (
    SelectDefinition(
        "wake_sensitivity",
        "Wake sensitivity",
        ("conservative", "normal", "high"),
        "mdi:ear-hearing",
    ),
    SelectDefinition(
        "wake_environment",
        "Wake environment",
        ("balanced", "tv_nearby", "strict", "far_field"),
        "mdi:home-sound-in-outline",
    ),
    SelectDefinition(
        "wake_sound",
        "Wake sound",
        tuple(str(row["value"]) for row in WAKE_SOUND_OPTIONS),
        "mdi:music-note",
    ),
    SelectDefinition(
        "led_listening_animation",
        "Listening animation",
        _ANIMATIONS,
        "mdi:led-strip-variant",
    ),
    SelectDefinition(
        "led_thinking_animation",
        "Thinking animation",
        _ANIMATIONS,
        "mdi:led-strip-variant",
    ),
    SelectDefinition(
        "led_tool_call_animation",
        "Tool-call animation",
        _ANIMATIONS,
        "mdi:led-strip-variant",
    ),
    SelectDefinition(
        "led_replying_animation",
        "Replying animation",
        _ANIMATIONS,
        "mdi:led-strip-variant",
    ),
    SelectDefinition(
        "logging_level",
        "Firmware logging",
        ("error", "warning", "info", "debug"),
        "mdi:text-box-search-outline",
    ),
)


async def async_setup_entry(
    hass,
    entry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Tater satellite select entities."""
    manager: TaterSatelliteManager = entry.runtime_data

    def factory(runtime: SatelliteRuntime):
        return [
            TaterPipelineSelect(runtime),
            TaterVadSelect(runtime),
            *[
                TaterSettingsSelect(runtime, definition)
                for definition in DEFINITIONS
                if not definition.key.startswith("led_")
                or board_supports_led_settings(runtime.board)
            ],
        ]

    manager.register_platform("select", factory, async_add_entities)


class TaterSettingsSelect(TaterSatelliteEntity, SelectEntity):
    """A selectable live firmware setting."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, runtime: SatelliteRuntime, definition: SelectDefinition) -> None:
        super().__init__(runtime, definition.key)
        self.definition = definition
        self._attr_name = definition.name
        self._attr_icon = definition.icon
        self._attr_options = list(definition.options)

    @property
    def current_option(self) -> str | None:
        """Return the current resolved setting."""
        value = str(self.runtime.effective_settings().get(self.definition.key) or "")
        return value if value in self.options else None

    async def async_select_option(self, option: str) -> None:
        """Set the firmware option."""
        if option not in self.options:
            raise ValueError(f"Unsupported option: {option}")
        await self.runtime.manager.async_set_device_settings(
            self.runtime.device_id, {self.definition.key: option}
        )


class TaterPipelineSelect(TaterSatelliteEntity, SelectEntity):
    """Select the Assist pipeline used by one satellite."""

    _attr_name = "Assist pipeline"
    _attr_icon = "mdi:pipe"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, runtime: SatelliteRuntime) -> None:
        super().__init__(runtime, "assist_pipeline")

    @property
    def options(self) -> list[str]:
        """Return current Assist pipeline names."""
        return [
            PREFERRED_PIPELINE,
            *[row["name"] for row in self.runtime.manager.pipelines_snapshot()],
        ]

    @property
    def current_option(self) -> str:
        """Return the selected pipeline name."""
        selected = str(self.runtime.record.get("pipeline_id") or "")
        for row in self.runtime.manager.pipelines_snapshot():
            if row["id"] == selected:
                return row["name"]
        return PREFERRED_PIPELINE

    async def async_added_to_hass(self) -> None:
        """Expose this entity id to AssistSatelliteEntity."""
        await super().async_added_to_hass()
        self.runtime.pipeline_entity_id = self.entity_id

    async def async_select_option(self, option: str) -> None:
        """Set the Assist pipeline."""
        pipeline_id = ""
        if option != PREFERRED_PIPELINE:
            for row in self.runtime.manager.pipelines_snapshot():
                if row["name"] == option:
                    pipeline_id = row["id"]
                    break
            if not pipeline_id:
                raise ValueError(f"Unknown Assist pipeline: {option}")
        await self.runtime.manager.async_set_device_settings(
            self.runtime.device_id, {}, pipeline_id=pipeline_id
        )


class TaterVadSelect(TaterSatelliteEntity, SelectEntity):
    """Select Home Assistant end-of-speech sensitivity."""

    _attr_name = "VAD sensitivity"
    _attr_icon = "mdi:account-voice"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, runtime: SatelliteRuntime) -> None:
        super().__init__(runtime, "vad_sensitivity")
        self._attr_options = ["default", "relaxed", "aggressive"]

    @property
    def current_option(self) -> str:
        """Return the current VAD sensitivity."""
        value = str(self.runtime.record.get("vad_sensitivity") or "default")
        return value if value in self.options else "default"

    async def async_added_to_hass(self) -> None:
        """Expose this entity id to AssistSatelliteEntity."""
        await super().async_added_to_hass()
        self.runtime.vad_entity_id = self.entity_id

    async def async_select_option(self, option: str) -> None:
        """Set VAD sensitivity."""
        if option not in self.options:
            raise ValueError(f"Unsupported VAD sensitivity: {option}")
        await self.runtime.manager.async_set_device_settings(
            self.runtime.device_id, {}, vad_sensitivity=option
        )
