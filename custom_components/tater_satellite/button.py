"""Button entities for Tater satellites."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .entity import TaterSatelliteEntity
from .manager import SatelliteRuntime, TaterSatelliteManager


async def async_setup_entry(
    hass,
    entry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up satellite buttons."""
    manager: TaterSatelliteManager = entry.runtime_data
    manager.register_platform(
        "button",
        lambda runtime: [TaterIdentifyButton(runtime)],
        async_add_entities,
    )


class TaterIdentifyButton(TaterSatelliteEntity, ButtonEntity):
    """Play a short tone on a satellite."""

    _attr_name = "Identify"
    _attr_icon = "mdi:map-marker-radius"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, runtime: SatelliteRuntime) -> None:
        super().__init__(runtime, "identify")

    async def async_press(self) -> None:
        """Identify this satellite."""
        await self.runtime.manager.async_identify(self.runtime.device_id)
