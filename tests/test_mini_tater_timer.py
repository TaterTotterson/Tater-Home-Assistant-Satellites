from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "mini_tater_timer", ROOT / "custom_components/tater_satellite/timer_tool.py"
)
assert SPEC is not None and SPEC.loader is not None
timer_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(timer_module)


class Satellite:
    def __init__(self, device_id="sat-1", name="Kitchen Echo", room="Kitchen"):
        self.device_id = device_id
        self.name = name
        self.room = room
        self.connected = True
        self.capabilities = {"timers": True}
        self.calls = []
        self.timers = []
        self.error = None

    async def async_request(self, command, payload, **kwargs):
        self.calls.append((command, payload, kwargs))
        if self.error:
            raise self.error
        if command == "timer.start":
            timer = {**payload, "state": "armed", "remaining_ms": payload["duration_ms"]}
            self.timers.append(timer)
            return {"ok": True, "timer": timer}
        if command == "timer.list":
            return {"ok": True, "timers": self.timers}
        selected = self.timers
        if not payload.get("all"):
            if payload.get("name"):
                selected = [row for row in selected if row["name"] == payload["name"]]
            if payload.get("original_duration_ms"):
                selected = [row for row in selected if row["original_duration_ms"] == payload["original_duration_ms"]]
            if not payload.get("name") and not payload.get("original_duration_ms"):
                ringing = [row for row in selected if row["state"] == "ringing"]
                if ringing:
                    selected = ringing[:1]
            if len(selected) > 1:
                return {"ok": True, "code": "ambiguous", "affected": 0, "timers": []}
        if command == "timer.cancel":
            self.timers = [row for row in self.timers if row not in selected]
        elif command == "timer.snooze":
            for row in selected:
                row.update(state="armed", remaining_ms=payload["duration_ms"], original_duration_ms=payload["duration_ms"])
        return {"ok": True, "affected": len(selected), "timers": selected}


class MiniTimerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.satellite = Satellite()
        self.other = Satellite("sat-2", "Office Echo", "Office")
        self.manager = SimpleNamespace(runtimes={"sat-1": self.satellite, "sat-2": self.other}, data={})
        self.tool = timer_module.TimerTool(self.manager)

    async def call(self, query, device_id="sat-1"):
        return await self.tool.async_call({"query": query}, None, device_id=device_id)

    def test_contract_is_natural_language_only_with_exact_verba_description(self):
        definition = self.tool.definition()["function"]
        self.assertEqual(definition["name"], "voicepe_remote_timer")
        self.assertEqual(set(definition["parameters"]["properties"]), {"query"})
        self.assertEqual(definition["parameters"]["required"], ["query"])
        self.assertFalse(definition["parameters"]["additionalProperties"])
        self.assertEqual(
            definition["description"],
            "Use this for normal timer requests. Set, start, create, cancel, stop, silence, snooze, or check multiple named timers from one natural-language request. "
            "Examples: set a pasta timer for 5 minutes; start a 90 second timer; how much time is left on the pasta timer; cancel the 10 minute timer.",
        )

    def test_spoken_numeric_fractional_and_clock_durations(self):
        for query, expected in [
            ("five minutes", 300),
            ("set a five minute timer", 300),
            ("ninety seconds", 90),
            ("twenty-five minutes", 1500),
            ("one and a half hours", 5400),
            ("half an hour", 1800),
            ("an hour and a half", 5400),
            ("a quarter hour", 900),
            ("1.5 hours", 5400),
            ("2.5 minutes", 150),
            ("1h 10m", 4200),
            ("1:30", 90),
            ("five hours", 7200),
        ]:
            with self.subTest(query=query):
                self.assertEqual(self.tool._parse_duration_to_seconds(query, 7200), expected)

    async def test_named_timers_start_on_origin_and_continue_as_separate_timers(self):
        first = await self.call("set a pasta timer for five minutes")
        second = await self.call("start a tea timer for ninety seconds")
        self.assertTrue(first["ok"])
        self.assertTrue(second["ok"])
        self.assertEqual([row["name"] for row in self.satellite.timers], ["pasta", "tea"])
        self.assertEqual([row["duration_ms"] for row in self.satellite.timers], [300000, 90000])
        self.assertNotEqual(self.satellite.timers[0]["id"], self.satellite.timers[1]["id"])
        self.assertEqual(self.other.calls, [])
        self.assertEqual(self.manager.data, {})

    async def test_duration_only_and_called_names(self):
        for query, expected in [
            ("set a 1.5 hour timer", ""),
            ("create a timer called pasta for five minutes", "pasta"),
            ("start a timer for five minutes called tea", "tea"),
        ]:
            with self.subTest(query=query):
                result = await self.call(query)
                self.assertTrue(result["ok"], result)
                self.assertEqual(self.satellite.timers[-1]["name"], expected)

    async def test_live_status_can_filter_names_and_original_durations(self):
        await self.call("set a pasta timer for five minutes")
        await self.call("set a tea timer for ninety seconds")
        self.satellite.timers[0]["remaining_ms"] = 120001
        result = await self.call("how much time is left on the pasta timer")
        self.assertEqual(self.satellite.calls[-1][0], "timer.list")
        self.assertEqual(result["data"]["timers"][0]["remaining_s"], 121)
        self.assertEqual(result["facts"]["affected"], 1)
        by_duration = await self.call("check the ninety second timer")
        self.assertEqual(by_duration["data"]["timers"][0]["name"], "tea")
        by_name = await self.call("check the pasta timer")
        self.assertEqual([row["name"] for row in by_name["data"]["timers"]], ["pasta"])
        all_timers = await self.call("list my timers")
        self.assertEqual(all_timers["facts"]["affected"], 2)
        shown = await self.call("show all my timers")
        self.assertEqual(shown["facts"]["affected"], 2)

    async def test_cancel_by_name_does_not_cancel_another_timer(self):
        await self.call("set a pasta timer for five minutes")
        await self.call("start a tea timer for one minute")
        result = await self.call("cancel the pasta timer")
        self.assertTrue(result["ok"])
        self.assertEqual([row["name"] for row in self.satellite.timers], ["tea"])

    async def test_cancel_by_original_duration_and_cancel_all(self):
        await self.call("set a five minute timer")
        await self.call("set a ten minute timer")
        result = await self.call("cancel the ten minute timer")
        self.assertTrue(result["ok"])
        self.assertEqual(len(self.satellite.timers), 1)
        self.assertEqual(self.satellite.calls[-1][1]["original_duration_ms"], 600000)
        await self.call("set a pasta timer for one minute")
        result = await self.call("cancel all my timers")
        self.assertTrue(result["ok"])
        self.assertTrue(self.satellite.calls[-1][1]["all"])
        self.assertEqual(self.satellite.timers, [])

    async def test_multiple_unnamed_candidates_require_clarification(self):
        await self.call("set a pasta timer for five minutes")
        await self.call("set a tea timer for two minutes")
        result = await self.call("cancel the timer")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "ambiguous_timer")
        self.assertEqual(len(self.satellite.timers), 2)

    async def test_silence_stops_the_ringing_timer_only(self):
        await self.call("set a pasta timer for five minutes")
        await self.call("set a tea timer for two minutes")
        self.satellite.timers[1]["state"] = "ringing"
        result = await self.call("silence the timer")
        self.assertTrue(result["ok"])
        self.assertEqual([row["name"] for row in self.satellite.timers], ["pasta"])

    async def test_snooze_defaults_to_five_minutes_and_supports_duration_selection(self):
        await self.call("set a ten minute timer")
        result = await self.call("snooze the timer")
        self.assertTrue(result["ok"])
        self.assertEqual(self.satellite.calls[-1][1]["duration_ms"], 300000)
        result = await self.call("snooze the five minute timer for two minutes")
        self.assertTrue(result["ok"])
        self.assertEqual(self.satellite.calls[-1][1]["original_duration_ms"], 300000)
        self.assertEqual(self.satellite.calls[-1][1]["duration_ms"], 120000)

    async def test_explicit_zero_snooze_does_not_silently_use_a_default(self):
        await self.call("set a five minute timer")
        result = await self.call("snooze the timer for zero minutes")
        self.assertFalse(result["ok"])
        self.assertEqual(len(self.satellite.calls), 1)

    async def test_chat_requires_target_and_can_name_a_satellite_or_room(self):
        missing = await self.call("set a timer for five minutes", "management-panel")
        self.assertFalse(missing["ok"])
        self.assertEqual(missing["code"], "missing_satellite")
        result = await self.call("set a pasta timer for five minutes on the Kitchen Echo", "management-panel")
        self.assertTrue(result["ok"])
        self.assertEqual(self.satellite.timers[0]["name"], "pasta")
        result = await self.call("start a tea timer in Office for one minute", "management-panel")
        self.assertTrue(result["ok"])
        self.assertEqual(self.other.timers[0]["name"], "tea")

    async def test_ambiguous_room_does_not_choose_an_arbitrary_satellite(self):
        self.other.room = "Kitchen"
        result = await self.call("set a timer for five minutes in Kitchen", "management-panel")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "ambiguous_satellite")
        self.assertEqual(self.satellite.calls + self.other.calls, [])

    async def test_unknown_explicit_location_never_falls_back_to_origin(self):
        result = await self.call("set a timer for five minutes in Garage")
        self.assertEqual(result["code"], "unknown_satellite")
        self.assertEqual(self.satellite.calls + self.other.calls, [])

    async def test_unavailable_and_unsupported_satellites_are_reported(self):
        self.satellite.connected = False
        result = await self.call("set a timer for five minutes")
        self.assertEqual(result["code"], "satellite_unavailable")
        self.satellite.connected = True
        self.satellite.capabilities = {}
        result = await self.call("set a timer for five minutes")
        self.assertEqual(result["code"], "timers_unsupported")
        self.assertEqual(self.satellite.calls, [])

    async def test_missing_duration_never_starts_a_timer(self):
        result = await self.call("set a pasta timer")
        self.assertEqual(result["code"], "missing_duration")
        self.assertEqual(self.satellite.calls, [])

    async def test_relative_now_uses_origin_and_negative_duration_is_rejected(self):
        result = await self.call("set a timer for five minutes from now")
        self.assertTrue(result["ok"])
        self.assertEqual(self.satellite.timers[0]["duration_ms"], 300000)
        result = await self.call("set a timer for -5 minutes")
        self.assertEqual(result["code"], "invalid_duration")
        self.assertEqual(len(self.satellite.calls), 1)

    async def test_unusual_duration_can_use_one_bounded_thanatos_fallback(self):
        requests = []

        async def infer(_prompt, payload):
            requests.append(payload)
            return {"seconds": 120}

        self.tool._llm_json = infer
        result = await self.call("set a timer for a couple of ticks")
        self.assertTrue(result["ok"])
        self.assertEqual(len(requests), 1)
        self.assertEqual(self.satellite.timers[0]["duration_ms"], 120000)

    async def test_timeout_does_not_retry_or_claim_timer_started(self):
        self.satellite.error = asyncio.TimeoutError()
        result = await self.call("set a timer for five minutes")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "timer_timeout")
        self.assertEqual(len(self.satellite.calls), 1)
        self.assertIn("unknown", result["error"])

    async def test_negative_ack_and_invalid_status_never_claim_success(self):
        for response in [{"ok": False, "message": "Timer limit reached"}, {"ok": True}]:
            async def reject(*args, **kwargs):
                return response

            self.satellite.async_request = reject
            self.assertFalse((await self.call("set a timer for five minutes"))["ok"])
            self.assertFalse((await self.call("check my timers"))["ok"])

    async def test_empty_status_is_verified_but_no_matching_cancel_is_not_a_completion(self):
        result = await self.call("check my timers")
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["timers"], [])
        self.assertFalse((await self.call("cancel the pasta timer"))["ok"])


if __name__ == "__main__":
    unittest.main()
