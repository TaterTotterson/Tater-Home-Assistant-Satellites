"""Firmware update entities for Tater satellites."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.components.update import UpdateEntity, UpdateEntityFeature
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import LATEST_FIRMWARE_URL
from .entity import TaterSatelliteEntity
from .firmware import display_version
from .manager import SatelliteRuntime, TaterSatelliteManager

SCAN_INTERVAL = timedelta(minutes=15)


async def async_setup_entry(
    hass,
    entry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up board-aware firmware updates."""
    manager: TaterSatelliteManager = entry.runtime_data
    manager.register_platform(
        "update",
        lambda runtime: [TaterFirmwareUpdate(runtime)],
        async_add_entities,
    )


class TaterFirmwareUpdate(TaterSatelliteEntity, UpdateEntity):
    """Tater Native OTA update entity."""

    _attr_name = "Firmware"
    _attr_icon = "mdi:chip"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_supported_features = (
        UpdateEntityFeature.INSTALL | UpdateEntityFeature.PROGRESS
    )
    _attr_release_url = LATEST_FIRMWARE_URL
    _attr_should_poll = True

    def __init__(self, runtime: SatelliteRuntime) -> None:
        super().__init__(runtime, "firmware")

    @property
    def available(self) -> bool:
        """Return whether release metadata is available."""
        return bool(
            self.runtime.manager.firmware.info_for_board(self.runtime.board).get(
                "firmware_version"
            )
        )

    @property
    def installed_version(self) -> str | None:
        """Return installed firmware."""
        return display_version(self.runtime.firmware_version) or None

    @property
    def latest_version(self) -> str | None:
        """Return latest board-matched firmware."""
        value = self.runtime.manager.firmware.info_for_board(self.runtime.board).get(
            "firmware_version"
        )
        return display_version(value) or None

    @property
    def in_progress(self) -> bool:
        """Return OTA state."""
        return self.runtime.ota_in_progress

    @property
    def update_percentage(self) -> int | None:
        """Return OTA progress."""
        return self.runtime.ota_progress

    async def async_update(self) -> None:
        """Refresh firmware release metadata."""
        await self.runtime.manager.firmware.async_refresh()

    async def async_install(self, version: str | None, backup: bool, **kwargs) -> None:
        """Install the latest OTA image."""
        await self.runtime.manager.async_install_firmware(self.runtime.device_id)
