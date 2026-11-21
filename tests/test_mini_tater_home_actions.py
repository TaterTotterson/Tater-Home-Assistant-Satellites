from __future__ import annotations

import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from test_tater_assistant import tater
from test_mini_tater_ha_tools import Services, entity


class HAHomeActionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.services = Services()
        self.home = tater.HomeControlTool(SimpleNamespace(services=self.services), lambda: {"entity_scope": "all"})
        self.rows = []
        self.home.entities = lambda **kwargs: self.rows
        self.home._allowed = lambda entity_id: any(row.entity_id == entity_id for row in self.rows)

    async def call(self, query):
        return await self.home.async_call({"query": query}, None)

    async def test_floor_request_changes_only_lights_on_that_floor(self):
        self.services.available.add(("light", "turn_off"))
        self.rows = [
            entity("light.office", "Desk", area="Office", floor="Upstairs"),
            entity("light.bedroom", "Bedroom", area="Bedroom", floor="Upstairs"),
            entity("light.kitchen", "Kitchen", floor="Downstairs"),
            entity("media_player.office", "Office speaker", area="Office", floor="Upstairs", supported_features=65535),
        ]
        result = await self.call("turn off the upstairs lights")
        self.assertTrue(result["ok"], result)
        self.assertEqual([call[2]["entity_id"] for call in self.services.calls], [["light.office"], ["light.bedroom"]])

    async def test_thermostat_fan_mode_uses_supported_values_without_touching_a_fan(self):
        self.services.available.add(("climate", "set_fan_mode"))
        self.rows = [
            entity("climate.office", "Office Thermostat", area="Office", fan_modes=["Auto", "On"]),
            entity("fan.office", "Office Fan", area="Office"),
        ]
        result = await self.call("set the office thermostat fan mode to auto")
        self.assertTrue(result["ok"], result)
        self.assertEqual(self.services.calls[-1][:3], ("climate", "set_fan_mode", {"entity_id": ["climate.office"], "fan_mode": "Auto"}))
        self.services.calls.clear()
        result = await self.call("set the office thermostat fan mode to turbo")
        self.assertFalse(result["ok"], result)
        self.assertEqual(self.services.calls, [])

    async def test_mower_and_media_commands_use_bounded_actions(self):
        self.rows = [entity("lawn_mower.garden", "Garden Mower", area="Garden"), entity("media_player.kitchen", "Kitchen Speaker", supported_features=65535)]
        for query, domain, service, extra in [
            ("start the garden mower", "lawn_mower", "start_mowing", {}),
            ("dock the garden mower", "lawn_mower", "dock", {}),
            ("mute the kitchen speaker", "media_player", "volume_mute", {"is_volume_muted": True}),
            ("unmute the kitchen speaker", "media_player", "volume_mute", {"is_volume_muted": False}),
            ("turn the kitchen speaker volume up", "media_player", "volume_up", {}),
        ]:
            self.services.available.add((domain, service))
            result = await self.call(query)
            self.assertTrue(result["ok"], (query, result))
            self.assertEqual(self.services.calls[-1][:2], (domain, service))
            for key, value in extra.items():
                self.assertEqual(self.services.calls[-1][2][key], value)

    async def test_vacuum_room_uses_cleaning_area_id_not_vacuums_location(self):
        self.rows = [entity("vacuum.robbie", "Robbie", area="Hall")]
        self.services.available.add(("vacuum", "clean_area"))
        areas = {"kitchen": SimpleNamespace(id="kitchen", name="Kitchen", aliases={"Cooking room"})}
        registry = SimpleNamespace(async_get=lambda hass: SimpleNamespace(areas=areas))
        with patch.dict(sys.modules, {"homeassistant.helpers": SimpleNamespace(area_registry=registry)}):
            result = await self.call("vacuum the cooking room")
            self.assertTrue(result["ok"], result)
            self.assertEqual(self.services.calls[-1][:3], ("vacuum", "clean_area", {"entity_id": ["vacuum.robbie"], "cleaning_area_id": ["kitchen"]}))
            self.rows.append(entity("vacuum.other", "Other", area="Hall"))
            self.services.calls.clear()
            result = await self.call("vacuum the kitchen")
            self.assertFalse(result["ok"])
            self.assertEqual(self.services.calls, [])

    async def test_misrouted_delayed_action_never_runs_immediately(self):
        self.rows = [entity("light.kitchen", "Kitchen")]
        self.services.available.add(("light", "turn_off"))
        for query in ("turn off the kitchen lights in five minutes", "turn off the kitchen lights tomorrow", "turn off the kitchen lights at 10 pm"):
            result = await self.call(query)
            self.assertFalse(result["ok"], result)
            self.assertIn("schedule_home", result["error"])
        self.assertEqual(self.services.calls, [])


if __name__ == "__main__":
    unittest.main()
