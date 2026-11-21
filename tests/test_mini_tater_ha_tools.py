from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from test_tater_assistant import tater, _Manager


def entity(entity_id, name, *, area="Kitchen", floor="", state="on", **attributes):
    return tater.HomeEntity(
        entity_id=entity_id, name=name, domain=entity_id.split(".")[0],
        area=area, floor=floor, state=state, aliases=(), attributes=attributes,
    )


class Services:
    def __init__(self):
        self.calls = []
        self.responses = {}
        self.available = set()
        self.error = None

    def has_service(self, domain, service):
        return (domain, service) in self.available

    async def async_call(self, domain, service, data, **kwargs):
        self.calls.append((domain, service, data, kwargs))
        if self.error:
            raise self.error
        return self.responses.get((domain, service))


class HAToolTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.manager = _Manager()
        self.services = Services()
        self.manager.hass.services = self.services
        self.manager.hass.config = SimpleNamespace(time_zone="America/Chicago")
        self.manager.runtimes = {}
        self.runtime = tater.MiniTaterRuntime(self.manager)
        self.runtime.setup()
        self.rows = [
            entity("todo.shopping", "Shopping", state="2"),
            entity("todo.work", "Work", state="0"),
            entity("weather.home", "Home", state="sunny", temperature=68, temperature_unit="°F"),
            entity("media_player.kitchen", "Kitchen Speaker", supported_features=65535),
        ]
        self.allowed = {row.entity_id for row in self.rows}
        self.runtime.home._allowed = lambda entity_id: entity_id in self.allowed
        self.runtime.home.entities = lambda *, domains=None: [
            row for row in self.rows if row.entity_id in self.allowed
            and (domains is None or row.domain in domains)
        ]
        self.runtime._device_llm_json = AsyncMock()

    async def call(self, tool, query, interpretation):
        self.runtime._device_llm_json.return_value = interpretation
        return await self.runtime.ha_tools[tool].async_call({"query": query}, "context", device_id="sat-1")

    def test_every_public_tool_remains_natural_language_only(self):
        for key, tool in self.runtime._execution_tools().items():
            definition = tool.definition()["function"]
            self.assertEqual(definition["name"], key)
            self.assertEqual(set(definition["parameters"]["properties"]), {"query"})
            self.assertFalse(definition["parameters"]["additionalProperties"])
        catalog = json.loads(self.runtime._astraeus_prompt().split("Astraeus stable execution catalog:\n")[1])
        self.assertEqual(set(catalog["available_tool_ids"]), set(self.runtime._execution_tools()))
        self.assertTrue(all(set(row) == {"id", "description"} for row in catalog["available_capabilities"]))

    async def test_clock_uses_ha_time_zone_in_every_model_request(self):
        self.runtime._post_json = AsyncMock(return_value={"choices": [{"message": {"content": "ok"}}]})
        from zoneinfo import ZoneInfo

        fake_time = SimpleNamespace(now=lambda: datetime(2026, 11, 20, 0, 15, tzinfo=timezone.utc))
        import sys
        with patch.dict(sys.modules, {"homeassistant.util": SimpleNamespace(dt=fake_time)}):
            for role in ("astraeus", "thanatos", "hermes"):
                await self.runtime._chat([{"role": "user", "content": "What day is it?"}], tools=False, role=role)
                messages = self.runtime._post_json.call_args.args[2]["messages"]
                clock = next(row["content"] for row in messages if row["content"].startswith("Current Local Date and Time:"))
                self.assertIn("Thursday, November 19, 2026 at 06:15 PM CST", clock)
                self.assertIn("America/Chicago", clock)
        self.assertEqual(datetime(2026, 11, 20, tzinfo=timezone.utc).astimezone(ZoneInfo("America/Chicago")).day, 19)

    async def test_lists_use_ha_storage_and_update_only_the_exact_item_uid(self):
        self.services.available = {("todo", "get_items"), ("todo", "add_item"), ("todo", "update_item"), ("todo", "remove_item")}
        self.services.responses["todo", "get_items"] = {
            "todo.shopping": {"items": [{"uid": "item-1", "summary": "Milk", "status": "needs_action"}]}
        }
        result = await self.call("todo_list", "add eggs to Shopping", {"action": "add", "entity_id": "todo.shopping", "item": "eggs"})
        self.assertTrue(result["ok"])
        self.assertEqual(self.services.calls[-1][2], {"entity_id": "todo.shopping", "item": "eggs"})
        result = await self.call("todo_list", "check off milk", {"action": "complete", "entity_id": "todo.shopping", "item": "milk"})
        self.assertTrue(result["ok"])
        self.assertEqual(self.services.calls[-1][2]["item"], "item-1")
        self.assertEqual(self.services.calls[-1][2]["status"], "completed")
        result = await self.call("todo_list", "what is on Shopping", {"action": "list", "entity_id": "todo.shopping"})
        self.assertEqual(result["items"][0]["summary"], "Milk")
        result = await self.call("todo_list", "delete milk", {"action": "remove", "entity_id": "todo.shopping", "item": "milk"})
        self.assertTrue(result["ok"])
        self.assertEqual(self.services.calls[-1][2]["item"], ["item-1"])

    async def test_unknown_or_unexposed_list_never_falls_back_to_another_list(self):
        self.services.available.add(("todo", "add_item"))
        for target in ("todo.missing", ""):
            result = await self.call("todo_list", "add milk to my missing list", {"action": "add", "entity_id": target, "item": "milk"})
            self.assertFalse(result["ok"])
        self.allowed.remove("todo.work")
        result = await self.call("todo_list", "add milk to work", {"action": "add", "entity_id": "todo.work", "item": "milk"})
        self.assertFalse(result["ok"])
        self.assertEqual(self.services.calls, [])

    async def test_exposure_is_rechecked_after_model_interpretation(self):
        async def interpret(*_args):
            self.allowed.remove("todo.shopping")
            return {"action": "add", "entity_id": "todo.shopping", "item": "eggs"}
        self.runtime._device_llm_json.side_effect = interpret
        result = await self.runtime.ha_tools["todo_list"].async_call({"query": "add eggs"}, None)
        self.assertFalse(result["ok"])
        self.assertEqual(self.services.calls, [])

    async def test_duplicate_list_item_names_require_clarification(self):
        self.services.available.add(("todo", "get_items"))
        self.services.responses["todo", "get_items"] = {
            "todo.shopping": {"items": [
                {"uid": str(i), "summary": "Milk", "status": "needs_action"} for i in (1, 2)
            ]}
        }
        result = await self.call("todo_list", "delete milk", {"action": "remove", "entity_id": "todo.shopping", "item": "milk"})
        self.assertFalse(result["ok"])
        self.assertEqual(len(self.services.calls), 1)

    async def test_weather_uses_current_ha_units_and_forecast_dates(self):
        result = await self.call("weather_forecast", "temperature outside", {"entity_id": "weather.home", "request_type": "current"})
        self.assertEqual(result["data"]["temperature"], 68)
        self.assertEqual(result["data"]["temperature_unit"], "°F")
        self.assertEqual(self.services.calls, [])
        self.services.available.add(("weather", "get_forecasts"))
        self.services.responses["weather", "get_forecasts"] = {
            "weather.home": {"forecast": [{"datetime": "2026-11-21T12:00:00-06:00", "condition": "rainy", "temperature": 55, "secret": "omit"}]}
        }
        result = await self.call("weather_forecast", "weather tomorrow", {"entity_id": "weather.home", "request_type": "forecast", "forecast_type": "daily"})
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["forecast"][0]["datetime"], "2026-11-21T12:00:00-06:00")
        self.assertNotIn("secret", result["data"]["forecast"][0])
        self.assertTrue(self.services.calls[-1][3]["return_response"])

    async def test_forecast_missing_or_unknown_location_is_an_error_not_invented_weather(self):
        self.services.available.add(("weather", "get_forecasts"))
        result = await self.call("weather_forecast", "tomorrow", {"entity_id": "weather.home", "request_type": "forecast"})
        self.assertFalse(result["ok"])
        result = await self.call("weather_forecast", "weather in Paris", {"entity_id": "weather.paris", "request_type": "current"})
        self.assertFalse(result["ok"])

    async def test_music_uses_public_ha_search_and_preserves_returned_media_uri(self):
        self.services.available = {("media_player", "search_media"), ("media_player", "play_media")}
        self.services.responses["media_player", "search_media"] = {
            "media_player.kitchen": {"result": [{"title": "Blue Train", "media_content_id": "provider://track/real-id", "media_content_type": "music"}]}
        }
        result = await self.call("music_assistant", "play Blue Train in the kitchen", {"action": "play", "entity_id": "media_player.kitchen", "media": "Blue Train", "media_type": "track"})
        self.assertTrue(result["ok"], result)
        self.assertEqual(self.services.calls[-1][2]["media_content_id"], "provider://track/real-id")
        self.assertIn("Requested playback", result["summary_for_user"])

    async def test_music_assistant_uses_existing_ha_service_without_new_credentials(self):
        self.rows[-1].attributes["mass_player_type"] = "player"
        self.services.available = {("music_assistant", "play_media")}
        result = await self.call("music_assistant", "queue Blue Train", {"action": "queue", "entity_id": "media_player.kitchen", "media": "Blue Train", "media_type": "album"})
        self.assertTrue(result["ok"], result)
        self.assertEqual(self.services.calls[-1][:2], ("music_assistant", "play_media"))
        self.assertEqual(self.services.calls[-1][2]["enqueue"], "add")

    async def test_music_failure_cannot_be_reported_as_success(self):
        self.services.available.add(("media_player", "volume_mute"))
        self.services.error = RuntimeError("player refused the action")
        result = await self.call("music_assistant", "mute kitchen", {"action": "mute", "entity_id": "media_player.kitchen"})
        self.assertFalse(result["ok"])
        self.assertIn("refused", result["error"])

    async def test_radio_search_uses_valid_ha_channel_media_class(self):
        self.services.available.add(("media_player", "search_media"))
        result = await self.call("music_assistant", "play jazz radio in the kitchen", {
            "action": "play", "entity_id": "media_player.kitchen", "media": "Jazz radio", "media_type": "radio",
        })
        self.assertFalse(result["ok"])
        self.assertEqual(self.services.calls[-1][2]["media_filter_classes"], ["channel"])

    async def test_broadcast_uses_configured_mini_tater_voice_and_reports_partial_failure(self):
        first = SimpleNamespace(
            device_id="sat-1", name="Kitchen", room="Kitchen", connected=True,
            server_base_url="http://ha", assist_entity=SimpleNamespace(entity_id="assist_satellite.kitchen", async_internal_announce=AsyncMock()),
        )
        second = SimpleNamespace(
            device_id="sat-2", name="Office", room="Office", connected=True,
            server_base_url="http://ha", assist_entity=SimpleNamespace(entity_id="assist_satellite.office", async_internal_announce=AsyncMock(side_effect=RuntimeError("offline"))),
        )
        self.manager.runtimes = {"sat-1": first, "sat-2": second}
        self.runtime.async_synthesize = AsyncMock(return_value=("audio/wav", b"audio"))
        result = await self.call("broadcast", "announce dinner is ready", {"explicit": True, "text": "Dinner is ready", "everywhere": True})
        self.assertFalse(result["ok"])
        self.assertEqual(result["sent"], ["Kitchen"])
        self.assertEqual(result["failed"][0]["satellite"], "Office")
        self.runtime.async_synthesize.assert_awaited_once_with("Dinner is ready")
        self.assertEqual(first.assist_entity.async_internal_announce.call_args.kwargs["message"], "Dinner is ready")

    async def test_unknown_broadcast_target_does_not_send_any_audio(self):
        self.runtime.async_synthesize = AsyncMock()
        result = await self.call("broadcast", "announce dinner in missing room", {"explicit": True, "text": "Dinner", "everywhere": False, "target_ids": ["missing"]})
        self.assertFalse(result["ok"])
        self.runtime.async_synthesize.assert_not_awaited()

    async def test_new_tool_still_executes_exactly_one_locked_hydra_instruction(self):
        self.services.available.add(("todo", "add_item"))
        self.runtime._device_llm_json.return_value = {"action": "add", "entity_id": "todo.shopping", "item": "eggs"}
        self.runtime._chat = AsyncMock(return_value={"tool_calls": [{"function": {"name": "todo_list", "arguments": json.dumps({"query": "add eggs to Shopping"})}}]})
        result = await self.runtime._run_thanatos_step(
            user_text="add eggs to Shopping", step={"tool_hint": "todo_list", "nl": "add eggs to Shopping"},
            previous_results=[], context=None,
        )
        self.assertTrue(result["ok"], result)
        definition = self.runtime._chat.call_args.kwargs["native_tools"][0]["function"]
        self.assertEqual(definition["name"], "todo_list")
        self.assertEqual(set(definition["parameters"]["properties"]), {"query"})
