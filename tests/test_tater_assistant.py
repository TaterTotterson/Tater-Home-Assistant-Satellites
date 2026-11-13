from __future__ import annotations

import asyncio
import importlib.util
import io
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
import wave


if "aiohttp" not in sys.modules and importlib.util.find_spec("aiohttp") is None:
    sys.modules["aiohttp"] = SimpleNamespace()


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "custom_components" / "tater_satellite" / "tater_assistant.py"
SPEC = importlib.util.spec_from_file_location("tater_satellite_tater_assistant", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
tater = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = tater
SPEC.loader.exec_module(tater)


class TaterSettingsTests(unittest.TestCase):
    def test_settings_normalize_and_never_publish_api_keys(self) -> None:
        settings = tater.normalize_tater_settings(
            {
                "assistant_mode": "tater",
                "entity_scope": "all",
                "llm_api_key": "secret",
                "max_llm": 500,
                "stt_wyoming_port": 0,
            }
        )

        self.assertEqual(settings["assistant_mode"], "tater")
        self.assertEqual(settings["entity_scope"], "all")
        self.assertEqual(settings["max_llm"], 100)
        self.assertEqual(settings["stt_wyoming_port"], 1)
        public = tater.public_tater_settings(settings)
        self.assertNotIn("llm_api_key", public)
        self.assertTrue(public["llm_api_key_set"])

    def test_pcm_is_wrapped_with_the_firmware_audio_format(self) -> None:
        payload = tater.pcm_to_wav(
            b"\x01\x00" * 160,
            {"rate": 16000, "width": 2, "channels": 1},
        )
        with wave.open(io.BytesIO(payload), "rb") as audio:
            self.assertEqual(audio.getframerate(), 16000)
            self.assertEqual(audio.getsampwidth(), 2)
            self.assertEqual(audio.getnchannels(), 1)
            self.assertEqual(audio.getnframes(), 160)

    def test_state_details_only_publish_useful_device_attributes(self) -> None:
        entity = tater.HomeEntity(
            entity_id="climate.office",
            name="Office",
            domain="climate",
            state="heat",
            area="Office",
            aliases=(),
            attributes={
                "current_temperature": 70,
                "unit_of_measurement": "°F",
                "access_token": "must-not-leave-home-assistant",
                "entity_picture": "/api/camera_proxy/camera.office?token=secret",
            },
        )

        attributes = entity.public(attributes=True)["attributes"]
        self.assertEqual(attributes["current_temperature"], 70)
        self.assertNotIn("access_token", attributes)
        self.assertNotIn("entity_picture", attributes)

    def test_manifest_uses_home_assistants_wyoming_dependency(self) -> None:
        manifest = json.loads(
            (ROOT / "custom_components" / "tater_satellite" / "manifest.json").read_text()
        )
        self.assertIn("wyoming", manifest["dependencies"])
        self.assertEqual(manifest["requirements"], [])


class _Services:
    def __init__(self) -> None:
        self.calls = []

    async def async_call(self, domain, service, data, *, blocking, context):
        self.calls.append((domain, service, data, blocking, context))


class HomeControlTests(unittest.IsolatedAsyncioTestCase):
    async def test_single_tool_dispatches_only_allowlisted_device_services(self) -> None:
        services = _Services()
        tool = tater.HomeControlTool(
            SimpleNamespace(services=services),
            lambda: {"entity_scope": "all"},
        )
        light = tater.HomeEntity(
            entity_id="light.kitchen",
            name="Kitchen",
            domain="light",
            state="off",
            area="Kitchen",
            aliases=(),
            attributes={},
        )
        tool.resolve = lambda _arguments: [light]
        tool._allowed = lambda _entity_id: True

        result = await tool.async_call(
            {
                "operation": "control",
                "command": "set_brightness",
                "entity_ids": ["light.kitchen"],
                "parameters": {"brightness_pct": 35, "malicious": "ignored"},
            },
            None,
        )

        self.assertTrue(result["ok"])
        self.assertEqual(
            services.calls,
            [
                (
                    "light",
                    "turn_on",
                    {"entity_id": ["light.kitchen"], "brightness_pct": 35},
                    True,
                    None,
                )
            ],
        )

    async def test_disallowed_command_cannot_become_an_arbitrary_service(self) -> None:
        services = _Services()
        tool = tater.HomeControlTool(SimpleNamespace(services=services), lambda: {"entity_scope": "all"})
        tool.resolve = lambda _arguments: [
            tater.HomeEntity(
                entity_id="switch.home_assistant",
                name="Home Assistant",
                domain="switch",
                state="on",
                area="Office",
                aliases=(),
                attributes={},
            )
        ]

        result = await tool.async_call(
            {"operation": "control", "command": "restart", "query": "home assistant"},
            None,
        )

        self.assertFalse(result["ok"])
        self.assertEqual(services.calls, [])

    async def test_generic_turn_on_cannot_unlock_or_mutate_a_lock(self) -> None:
        services = _Services()
        tool = tater.HomeControlTool(SimpleNamespace(services=services), lambda: {"entity_scope": "all"})
        tool.resolve = lambda _arguments: [
            tater.HomeEntity(
                entity_id="lock.front_door",
                name="Front door",
                domain="lock",
                state="locked",
                area="Entry",
                aliases=(),
                attributes={},
            )
        ]

        result = await tool.async_call(
            {"operation": "control", "command": "turn_on", "query": "front door"},
            None,
        )

        self.assertFalse(result["ok"])
        self.assertEqual(services.calls, [])


class _Manager:
    def __init__(self) -> None:
        self.hass = SimpleNamespace()
        self.data = {
            "tater_settings": {
                **tater.DEFAULT_TATER_SETTINGS,
                "assistant_mode": "tater",
                "llm_model": "test-model",
                "llm_api_key": "secret",
                "hydra_astraeus_plan_review_enabled": False,
            }
        }
        self.saved = 0

    async def async_save(self) -> None:
        self.saved += 1


class _Home:
    def __init__(self) -> None:
        self.calls = []

    @staticmethod
    def definition():
        return tater.HomeControlTool.definition()

    @staticmethod
    def summary():
        return "- light.kitchen | Kitchen | Kitchen | off"

    async def async_call(self, arguments, context):
        self.calls.append((arguments, context))
        return {"ok": True, "performed": [{"domain": "light", "service": "turn_on"}]}


class MiniHydraTests(unittest.IsolatedAsyncioTestCase):
    def test_generated_speech_cache_is_bounded(self) -> None:
        runtime = tater.MiniTaterRuntime(_Manager())
        for index in range(tater.MAX_STORED_SPEECH_CLIPS + 5):
            runtime.store_clip("audio/wav", str(index).encode())

        self.assertEqual(len(runtime._clips), tater.MAX_STORED_SPEECH_CLIPS)

    def test_local_openai_compatible_endpoints_can_run_without_keys(self) -> None:
        manager = _Manager()
        manager.data["tater_settings"].update(
            {
                "llm_base_url": "http://llm.local/v1",
                "llm_api_key": "",
                "stt_base_url": "http://speech.local/v1",
                "stt_api_key": "",
                "tts_base_url": "http://speech.local/v1",
                "tts_api_key": "",
            }
        )
        runtime = tater.MiniTaterRuntime(manager)
        runtime.setup()

        self.assertEqual(runtime.ready_status()["missing"], [])

    async def test_turn_exposes_only_control_home_and_records_the_ledger(self) -> None:
        manager = _Manager()
        runtime = tater.MiniTaterRuntime(manager)
        runtime.setup()
        home = _Home()
        runtime.home = home
        responses = [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call-1",
                        "type": "function",
                        "function": {
                            "name": "control_home",
                            "arguments": '{"operation":"control","command":"turn_on","entity_ids":["light.kitchen"]}',
                        },
                    }
                ],
            },
            {"role": "assistant", "content": "The kitchen light is on."},
        ]

        async def fake_chat(messages, *, tools=True):
            if tools:
                definition = runtime.home.definition()
                self.assertEqual(definition["function"]["name"], "control_home")
            return responses.pop(0)

        runtime._chat = fake_chat
        result = await runtime.async_process_text(
            "Turn on the kitchen light",
            conversation_id="conversation-1",
            device_id="satellite-1",
        )

        self.assertEqual(result["response"], "The kitchen light is on.")
        self.assertEqual(len(home.calls), 1)
        ledger = manager.data["tater_hydra_ledger"]
        self.assertEqual(ledger[-1]["outcome"], "done")
        self.assertEqual(ledger[-1]["tools"][0]["name"], "control_home")
        self.assertGreater(manager.saved, 0)

    def test_voice_entity_has_separate_home_assistant_and_tater_paths(self) -> None:
        source = (ROOT / "custom_components/tater_satellite/assist_satellite.py").read_text()
        self.assertIn('== "tater"', source)
        self.assertIn("async_run_voice(", source)
        self.assertIn("async_accept_pipeline_from_satellite(", source)


if __name__ == "__main__":
    unittest.main()
