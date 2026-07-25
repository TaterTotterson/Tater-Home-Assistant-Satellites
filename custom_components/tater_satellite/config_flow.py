"""Config flow for Tater Satellite."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult

from .const import DOMAIN, NAME


class TaterSatelliteConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Configure the Tater Satellite integration."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Create the single adapter entry."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        if user_input is not None:
            return self.async_create_entry(title=NAME, data={})
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({}),
        )
