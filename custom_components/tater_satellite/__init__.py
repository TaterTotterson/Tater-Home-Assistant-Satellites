"""Tater Native satellites for Home Assistant."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from urllib.parse import quote

from homeassistant.components import frontend, panel_custom
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.device_registry import DeviceEntry
from homeassistant.loader import async_get_integration

from .const import (
    DATA_MANAGER,
    DATA_PANEL_REGISTERED,
    DOMAIN,
    PANEL_ELEMENT,
    PANEL_STATIC_URL,
    PANEL_URL_PATH,
    PLATFORMS,
)
from .http import VIEWS
from .manager import TaterSatelliteManager

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

TaterConfigEntry = ConfigEntry


def _panel_element_name(version: str) -> str:
    """Return a version-specific element so a live HA tab cannot reuse stale UI."""
    version_slug = re.sub(r"[^a-z0-9]+", "-", version.lower()).strip("-")
    return f"{PANEL_ELEMENT}-{version_slug or 'dev'}"


def _panel_asset_revision(path: Path) -> str:
    """Give an updated panel a fresh module and custom-element identity."""
    digest = hashlib.sha256(path.read_bytes())
    for dependency in sorted(path.parent.glob("*.js")):
        if dependency != path:
            digest.update(dependency.name.encode())
            digest.update(dependency.read_bytes())
    return digest.hexdigest()[:12]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Register shared HTTP routes and frontend assets."""
    hass.data.setdefault(DOMAIN, {})
    for view in VIEWS:
        hass.http.register_view(view)
    frontend_root = Path(__file__).parent / "frontend"
    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(
                PANEL_STATIC_URL,
                str(frontend_root),
                cache_headers=False,
            )
        ]
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: TaterConfigEntry) -> bool:
    """Set up Tater Satellite from a config entry."""
    manager = TaterSatelliteManager(hass, entry)
    await manager.async_setup()
    entry.runtime_data = manager
    hass.data[DOMAIN][DATA_MANAGER] = manager

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    if not hass.data[DOMAIN].get(DATA_PANEL_REGISTERED):
        integration = await async_get_integration(hass, DOMAIN)
        panel_revision = await hass.async_add_executor_job(
            _panel_asset_revision,
            Path(__file__).parent / "frontend" / "tater-satellite-panel.js",
        )
        panel_version = f"{integration.version or 'dev'}-{panel_revision}"
        await panel_custom.async_register_panel(
            hass,
            frontend_url_path=PANEL_URL_PATH,
            webcomponent_name=_panel_element_name(panel_version),
            sidebar_title="Tater Satellites",
            sidebar_icon="mdi:account-voice",
            module_url=(
                f"{PANEL_STATIC_URL}/tater-satellite-panel.js"
                f"?v={quote(panel_version, safe='')}"
            ),
            require_admin=True,
            config_panel_domain=DOMAIN,
        )
        hass.data[DOMAIN][DATA_PANEL_REGISTERED] = True
    return True


async def async_unload_entry(hass: HomeAssistant, entry: TaterConfigEntry) -> bool:
    """Unload a Tater Satellite entry."""
    manager: TaterSatelliteManager = entry.runtime_data
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if not unloaded:
        return False
    await manager.async_shutdown()
    if hass.data.get(DOMAIN, {}).get(DATA_MANAGER) is manager:
        hass.data[DOMAIN].pop(DATA_MANAGER, None)
    frontend.async_remove_panel(hass, PANEL_URL_PATH, warn_if_unknown=False)
    hass.data.get(DOMAIN, {}).pop(DATA_PANEL_REGISTERED, None)
    return True


async def async_remove_config_entry_device(
    hass: HomeAssistant, config_entry: TaterConfigEntry, device_entry: DeviceEntry
) -> bool:
    """Allow deleting an offline or stale Tater satellite device from HA.

    Returning True lets HA remove the device (and its entities). Connected
    satellites, saved stereo pairs, and devices without a Tater identifier
    are rejected. An offline satellite is forgotten first so its credential
    cannot bring the device back.
    """
    manager = getattr(config_entry, "runtime_data", None)
    if not isinstance(manager, TaterSatelliteManager):
        # Without a loaded manager the stored credential cannot be removed.
        return False
    device_ids = [
        identifier
        for domain, identifier in device_entry.identifiers
        if domain == DOMAIN
    ]
    if not device_ids:
        return False
    pairs = manager.data.get("stereo_pairs")
    pair_targets = {
        pair.get("target")
        for pair in (pairs.values() if isinstance(pairs, dict) else ())
        if isinstance(pair, dict)
    }
    if any(device_id in pair_targets for device_id in device_ids):
        # Stereo pairs are managed from the panel; HA would recreate the device.
        return False
    runtimes = [
        manager.runtimes[device_id]
        for device_id in device_ids
        if device_id in manager.runtimes
    ]
    if any(runtime.connected for runtime in runtimes):
        return False
    for device_id in device_ids:
        if device_id in manager.runtimes:
            await manager.async_forget(device_id)
    return True
