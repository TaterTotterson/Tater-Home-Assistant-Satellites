from __future__ import annotations

import asyncio
import base64
import importlib.util
import io
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch
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
    def test_home_assistant_mode_is_the_default(self) -> None:
        self.assertEqual(
            tater.normalize_tater_settings({})["assistant_mode"],
            "home_assistant",
        )
        self.assertEqual(
            tater.normalize_tater_settings({"assistant_mode": "unknown"})[
                "assistant_mode"
            ],
            "home_assistant",
        )

    def test_wyoming_optional_names_default_to_blank(self) -> None:
        settings = tater.normalize_tater_settings(
            {
                "stt_provider": "wyoming",
                "stt_model": "gpt-4o-transcribe",
                "tts_provider": "wyoming",
                "tts_voice": "alloy",
            }
        )

        self.assertEqual(settings["stt_wyoming_model"], "")
        self.assertEqual(settings["tts_wyoming_voice"], "")

    def test_custom_legacy_wyoming_names_are_migrated(self) -> None:
        settings = tater.normalize_tater_settings(
            {
                "stt_provider": "wyoming",
                "stt_model": "custom-asr",
                "tts_provider": "wyoming",
                "tts_voice": "custom-voice",
            }
        )

        self.assertEqual(settings["stt_wyoming_model"], "custom-asr")
        self.assertEqual(settings["tts_wyoming_voice"], "custom-voice")

    def test_settings_normalize_and_never_publish_api_keys(self) -> None:
        settings = tater.normalize_tater_settings(
            {
                "assistant_mode": "tater",
                "entity_scope": "all",
                "llm_api_key": "secret",
                "max_llm": 500,
                "stt_wyoming_port": 0,
                "vad_backend": "webrtc",
            }
        )

        self.assertEqual(settings["assistant_mode"], "tater")
        self.assertEqual(settings["entity_scope"], "all")
        self.assertEqual(settings["max_llm"], 100)
        self.assertEqual(settings["stt_wyoming_port"], 1)
        self.assertNotIn("vad_backend", settings)
        public = tater.public_tater_settings(settings)
        self.assertNotIn("llm_api_key", public)
        self.assertTrue(public["llm_api_key_set"])

    def test_vision_defaults_to_base_and_dedicated_secrets_stay_private(self) -> None:
        defaults = tater.normalize_tater_settings({})
        self.assertEqual(defaults["vision_provider"], "base")
        self.assertEqual(defaults["vision_base_url"], "")

        settings = tater.normalize_tater_settings(
            {
                "vision_provider": "openai_compatible",
                "vision_base_url": "http://vision.local:1234/v1",
                "vision_model": "vision-model",
                "vision_api_key": "vision-secret",
            }
        )
        public = tater.public_tater_settings(settings)

        self.assertEqual(settings["vision_provider"], "openai_compatible")
        self.assertEqual(settings["vision_base_url"], "http://vision.local:1234/v1")
        self.assertNotIn("vision_api_key", public)
        self.assertTrue(public["vision_api_key_set"])

    def test_vision_image_validation_is_bounded_and_keeps_metadata(self) -> None:
        data_url = "data:image/png;base64," + base64.b64encode(b"small image").decode()
        images = tater.normalize_vision_images(
            [{"name": "kitchen.png", "data_url": data_url}]
        )

        self.assertEqual(images[0]["name"], "kitchen.png")
        self.assertEqual(images[0]["mime_type"], "image/png")
        self.assertEqual(images[0]["size_bytes"], len(b"small image"))
        with self.assertRaisesRegex(ValueError, "JPEG, PNG, WebP, or GIF"):
            tater.normalize_vision_images(
                [{"name": "bad.svg", "data_url": "data:image/svg+xml;base64,PHN2Zz4="}]
            )

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

    def test_micro_vad_scores_fixed_ten_millisecond_frames(self) -> None:
        class FakeMicroVad:
            def __init__(self):
                self.calls = []

            def Process10ms(self, frame):
                self.calls.append(frame)
                return (-1.0, 0.72)[len(self.calls) - 1]

        with patch.object(
            tater.importlib,
            "import_module",
            return_value=SimpleNamespace(MicroVad=FakeMicroVad),
        ):
            backend = tater._MicroVadBackend()

        self.assertEqual(backend.process(b"\0" * 640), 0.72)
        self.assertEqual(len(backend._vad.calls), 2)

class _Services:
    def __init__(self) -> None:
        self.calls = []

    async def async_call(self, domain, service, data, *, blocking, context):
        self.calls.append((domain, service, data, blocking, context))


class HomeControlTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def _homeassistant_modules(data_key="exposed_entities"):
        homeassistant = SimpleNamespace(__path__=[])
        components = SimpleNamespace(__path__=[])
        homeassistant_component = SimpleNamespace(__path__=[])
        const = SimpleNamespace(DATA_EXPOSED_ENTITIES=data_key)
        return {
            "homeassistant": homeassistant,
            "homeassistant.components": components,
            "homeassistant.components.homeassistant": homeassistant_component,
            "homeassistant.components.homeassistant.const": const,
        }

    def test_exposed_scope_uses_current_home_assistant_api(self) -> None:
        exposed = SimpleNamespace(
            async_should_expose=lambda assistant, entity_id: (
                assistant == "conversation" and entity_id == "light.kitchen"
            )
        )
        tool = tater.HomeControlTool(
            SimpleNamespace(data={"exposed_entities": exposed}),
            lambda: {"entity_scope": "exposed"},
        )

        with patch.dict(sys.modules, self._homeassistant_modules()):
            self.assertTrue(tool._allowed("light.kitchen"))
            self.assertFalse(tool._allowed("light.office"))

    def test_exposed_scope_keeps_legacy_non_mutating_api_compatibility(self) -> None:
        calls = []
        exposed = SimpleNamespace(
            async_get_should_expose=lambda assistant, entity_id: calls.append(
                (assistant, entity_id)
            )
            or True,
            async_should_expose=lambda *_args: self.fail(
                "legacy exposure lookup should be preferred when available"
            ),
        )
        tool = tater.HomeControlTool(
            SimpleNamespace(data={"exposed_entities": exposed}),
            lambda: {"entity_scope": "exposed"},
        )

        with patch.dict(sys.modules, self._homeassistant_modules()):
            self.assertTrue(tool._allowed("switch.desk"))

        self.assertEqual(calls, [("conversation", "switch.desk")])

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
        tool.resolve = lambda _arguments, **_kwargs: [light]
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
        self.assertEqual(result["summary_for_user"], "Set Kitchen to 35% brightness.")
        self.assertEqual(result["facts"], {"action": "set_brightness", "success_count": 1, "failure_count": 0})
        self.assertEqual(result["performed"][0]["name"], "Kitchen")
        self.assertEqual(result["performed"][0]["area"], "Kitchen")
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

    async def test_one_control_step_can_change_several_devices(self) -> None:
        services = _Services()
        tool = tater.HomeControlTool(
            SimpleNamespace(services=services), lambda: {"entity_scope": "all"}
        )
        lights = [
            tater.HomeEntity(
                "light.kitchen", "Kitchen light", "light", "on", "Kitchen", (), {}
            ),
            tater.HomeEntity(
                "light.dining", "Dining light", "light", "on", "Dining", (), {}
            ),
        ]
        tool.resolve = lambda _arguments, **_kwargs: lights
        tool._allowed = lambda _entity_id: True

        result = await tool.async_call(
            {
                "operation": "control",
                "command": "turn_off",
                "entity_ids": ["light.kitchen", "light.dining"],
            },
            None,
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["facts"]["success_count"], 2)
        self.assertEqual(
            [call[2]["entity_id"] for call in services.calls],
            [["light.kitchen"], ["light.dining"]],
        )

    async def test_device_control_accepts_the_verba_natural_language_contract(self) -> None:
        services = _Services()
        tool = tater.HomeControlTool(
            SimpleNamespace(services=services), lambda: {"entity_scope": "all"}
        )
        office_light = tater.HomeEntity(
            "light.office_ceiling",
            "Office ceiling lights",
            "light",
            "on",
            "Office",
            ("Office lights",),
            {},
        )
        office_player = tater.HomeEntity(
            "media_player.office_satellite",
            "Office satellite",
            "media_player",
            "idle",
            "Office",
            (),
            {"supported_features": 4 | 4096},
        )
        tool.entities = lambda: [office_player, office_light]
        tool._allowed = lambda _entity_id: True

        result = await tool.async_call(
            {"query": "turn off the office ceiling lights"},
            None,
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["facts"]["action"], "turn_off")
        self.assertEqual(
            services.calls,
            [("light", "turn_off", {"entity_id": ["light.office_ceiling"]}, True, None)],
        )

    def test_device_control_natural_language_extracts_values_and_query_only_schema(self) -> None:
        definition = tater.HomeControlTool.definition()["function"]
        self.assertEqual(definition["name"], "device_control")
        self.assertEqual(definition["parameters"]["required"], ["query"])
        self.assertEqual(set(definition["parameters"]["properties"]), {"query"})
        brightness = tater.HomeControlTool._natural_arguments(
            "set the kitchen lights to 35 percent"
        )
        temperature = tater.HomeControlTool._natural_arguments(
            "set the hallway thermostat to 72 degrees"
        )
        status = tater.HomeControlTool._natural_arguments(
            "is the bedroom fan on?"
        )

        self.assertEqual(brightness["command"], "set_brightness")
        self.assertEqual(brightness["parameters"], {"brightness_pct": 35})
        self.assertEqual(brightness["query"], "kitchen")
        self.assertEqual(temperature["command"], "set_temperature")
        self.assertEqual(temperature["parameters"], {"temperature": 72.0})
        self.assertEqual(status["operation"], "get_state")
        self.assertEqual(status["query"], "bedroom")

    async def test_device_control_uses_bounded_llm_fallback_and_chooser(self) -> None:
        services = _Services()
        llm_calls = []

        async def llm_json(system, payload):
            llm_calls.append((system, payload))
            if "Interpret one" in system:
                return {
                    "operation": "control",
                    "command": "turn_off",
                    "target": "office",
                    "parameters": {},
                }
            return {"entity_id": "light.dining_table"}

        tool = tater.HomeControlTool(
            SimpleNamespace(services=services),
            lambda: {"entity_scope": "all"},
            llm_json,
        )
        office = tater.HomeEntity(
            "light.office", "Office light", "light", "on", "Office", (), {}
        )
        kitchen_table = tater.HomeEntity(
            "light.kitchen_table", "Kitchen table light", "light", "off", "Kitchen", (), {}
        )
        dining_table = tater.HomeEntity(
            "light.dining_table", "Dining table light", "light", "off", "Dining", (), {}
        )
        tool.entities = lambda: [office, kitchen_table, dining_table]
        tool._allowed = lambda _entity_id: True

        interpreted = await tool.async_call(
            {"query": "extinguish the office lights"}, None
        )
        selected = await tool.async_call(
            {"query": "turn on the table light"}, None
        )

        self.assertTrue(interpreted["ok"])
        self.assertTrue(selected["ok"])
        self.assertEqual(services.calls[0][2]["entity_id"], ["light.office"])
        self.assertEqual(services.calls[1][2]["entity_id"], ["light.dining_table"])
        self.assertEqual(len(llm_calls), 2)

    async def test_natural_device_control_does_not_broaden_a_missing_target(self) -> None:
        services = _Services()
        tool = tater.HomeControlTool(
            SimpleNamespace(services=services), lambda: {"entity_scope": "all"}
        )
        tool.entities = lambda: [
            tater.HomeEntity(
                "light.kitchen", "Kitchen light", "light", "on", "Kitchen", (), {}
            ),
            tater.HomeEntity(
                "light.bedroom", "Bedroom light", "light", "on", "Bedroom", (), {}
            ),
        ]

        result = await tool.async_call({"query": "turn off the lights"}, None)

        self.assertFalse(result["ok"])
        self.assertEqual(result["needs"], ["Which room or device should I use?"])
        self.assertEqual(services.calls, [])

    async def test_disallowed_command_cannot_become_an_arbitrary_service(self) -> None:
        services = _Services()
        tool = tater.HomeControlTool(SimpleNamespace(services=services), lambda: {"entity_scope": "all"})
        tool.resolve = lambda _arguments, **_kwargs: [
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
        tool.resolve = lambda _arguments, **_kwargs: [
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

    def test_shop_verba_targeting_keeps_office_lights_in_the_light_domain(self) -> None:
        tool = tater.HomeControlTool(SimpleNamespace(), lambda: {"entity_scope": "all"})
        office_light = tater.HomeEntity(
            entity_id="light.office_ceiling",
            name="Office ceiling lights",
            domain="light",
            state="on",
            area="Office",
            aliases=("Office lights",),
            attributes={},
        )
        office_satellite = tater.HomeEntity(
            entity_id="media_player.office_tater_sat1_media_player",
            name="Office Tater Sat1 media player",
            domain="media_player",
            state="idle",
            area="Office",
            aliases=(),
            attributes={"supported_features": 4 | 4096},
        )
        office_switch = tater.HomeEntity(
            entity_id="switch.office_printer",
            name="Office printer",
            domain="switch",
            state="on",
            area="Office",
            aliases=(),
            attributes={},
        )
        tool.entities = lambda: [office_satellite, office_switch, office_light]

        matches = tool.resolve(
            {
                "entity_ids": [office_satellite.entity_id],
                "query": "Office Tater Sat1 media player",
                "domain": "media_player",
            },
            request="Turn the office lights off",
        )

        self.assertEqual([row.entity_id for row in matches], [office_light.entity_id])

    def test_compound_request_keeps_each_atomic_query_on_its_own_target(self) -> None:
        tool = tater.HomeControlTool(SimpleNamespace(), lambda: {"entity_scope": "all"})
        kitchen_light = tater.HomeEntity(
            entity_id="light.kitchen",
            name="Kitchen ceiling light",
            domain="light",
            state="on",
            area="Kitchen",
            aliases=(),
            attributes={},
        )
        bedroom_fan = tater.HomeEntity(
            entity_id="fan.bedroom",
            name="Bedroom fan",
            domain="fan",
            state="off",
            area="Bedroom",
            aliases=(),
            attributes={},
        )
        tool.entities = lambda: [kitchen_light, bedroom_fan]
        request = "Turn the kitchen light off and the bedroom fan on"

        light_matches = tool.resolve(
            {"operation": "control", "command": "turn_off", "query": "kitchen light"},
            request=request,
        )
        fan_matches = tool.resolve(
            {"operation": "control", "command": "turn_on", "query": "bedroom fan"},
            request=request,
        )

        self.assertEqual([row.entity_id for row in light_matches], ["light.kitchen"])
        self.assertEqual([row.entity_id for row in fan_matches], ["fan.bedroom"])

    def test_compound_same_domain_request_does_not_broaden_atomic_queries(self) -> None:
        tool = tater.HomeControlTool(SimpleNamespace(), lambda: {"entity_scope": "all"})
        kitchen = tater.HomeEntity(
            "light.kitchen", "Kitchen light", "light", "on", "Kitchen", (), {}
        )
        bedroom = tater.HomeEntity(
            "light.bedroom", "Bedroom light", "light", "off", "Bedroom", (), {}
        )
        tool.entities = lambda: [kitchen, bedroom]
        request = "Turn the kitchen light off and the bedroom light on"

        off_matches = tool.resolve(
            {"operation": "control", "command": "turn_off", "query": "kitchen light"},
            request=request,
        )
        on_matches = tool.resolve(
            {"operation": "control", "command": "turn_on", "query": "bedroom light"},
            request=request,
        )

        self.assertEqual([row.entity_id for row in off_matches], ["light.kitchen"])
        self.assertEqual([row.entity_id for row in on_matches], ["light.bedroom"])

    def test_unsupported_media_player_power_is_filtered_by_features(self) -> None:
        player = tater.HomeEntity(
            entity_id="media_player.office_tater_sat1_media_player",
            name="Office Tater Sat1 media player",
            domain="media_player",
            state="idle",
            area="Office",
            aliases=(),
            attributes={"supported_features": 4 | 4096},
        )

        self.assertFalse(tater.HomeControlTool._supports_command(player, "turn_off"))
        self.assertTrue(tater.HomeControlTool._supports_command(player, "set_volume"))
        self.assertTrue(tater.HomeControlTool._supports_command(player, "media_stop"))

    async def test_home_assistant_service_rejection_becomes_a_tool_failure(self) -> None:
        class RejectingServices:
            @staticmethod
            def has_service(_domain, _service):
                return True

            @staticmethod
            async def async_call(_domain, _service, _data, *, blocking, context):
                raise RuntimeError("entity does not support this action")

        light = tater.HomeEntity(
            entity_id="light.office",
            name="Office light",
            domain="light",
            state="on",
            area="Office",
            aliases=(),
            attributes={},
        )
        tool = tater.HomeControlTool(
            SimpleNamespace(services=RejectingServices()),
            lambda: {"entity_scope": "all"},
        )
        tool.resolve = lambda _arguments, **_kwargs: [light]
        tool._allowed = lambda _entity_id: True

        result = await tool.async_call(
            {"operation": "control", "command": "turn_off", "query": "office lights"},
            None,
            request="Turn the office lights off",
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["failures"][0]["entity_id"], "light.office")


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

    async def async_call(self, arguments, context, *, request=""):
        self.calls.append((arguments, context, request))
        return {
            "ok": True,
            "performed": [
                {
                    "domain": "light",
                    "service": "turn_on",
                    "entity_ids": ["light.kitchen"],
                    "name": "Kitchen light",
                    "area": "Kitchen",
                }
            ],
            "summary_for_user": "Turned on Kitchen light.",
            "say_hint": "Report the verified outcome naturally and briefly.",
        }


class _Vision:
    def __init__(self) -> None:
        self.calls = []

    @staticmethod
    def definition():
        return tater.TaterVisionTool.definition()

    async def async_call(self, arguments, context, *, request="", device_id=""):
        self.calls.append((arguments, context, request, device_id))
        return {
            "ok": True,
            "summary_for_user": "The dog is resting by the back door.",
            "data": {
                "description": "The dog is resting by the back door.",
            },
            "say_hint": "Answer from the returned visual description.",
        }


class MiniHydraTests(unittest.IsolatedAsyncioTestCase):
    class _TestVad:
        @staticmethod
        def process(chunk):
            sample = int.from_bytes(chunk[:2], "little", signed=True)
            return 1.0 if abs(sample) >= 450 else 0.0

    @staticmethod
    async def _audio_stream(chunks):
        for chunk in chunks:
            yield chunk

    @staticmethod
    def _pcm_chunk(amplitude: int, samples: int = 320) -> bytes:
        return int(amplitude).to_bytes(2, "little", signed=True) * samples

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

    def test_astraeus_gets_descriptions_without_usage_and_thanatos_gets_native_contracts(self) -> None:
        runtime = tater.MiniTaterRuntime(_Manager())
        prompt = runtime._astraeus_prompt()

        self.assertIn('"available_tool_ids":["device_control","tater_vision"]', prompt)
        self.assertIn('"id":"device_control","description"', prompt)
        self.assertIn('"id":"tater_vision","description"', prompt)
        self.assertNotIn('"usage"', prompt)
        self.assertNotIn('"how_to_use"', prompt)
        self.assertIn(tater.DEVICE_CONTROL_VERBA_DESCRIPTION, prompt)
        self.assertIn(tater.TATER_VISION_VERBA_DESCRIPTION, prompt)
        self.assertEqual(
            tater.HomeControlTool.definition()["function"]["description"],
            tater.DEVICE_CONTROL_VERBA_DESCRIPTION,
        )
        self.assertEqual(
            tater.TaterVisionTool.definition()["function"]["description"],
            tater.TATER_VISION_VERBA_DESCRIPTION,
        )
        self.assertEqual(
            tater.HomeControlTool.definition()["function"]["parameters"]["required"],
            ["query"],
        )
        self.assertEqual(
            tater.TaterVisionTool.definition()["function"]["parameters"]["required"],
            ["query"],
        )

    def test_tater_vision_selects_named_camera_outdoor_area_and_asking_room(self) -> None:
        cameras = [
            {
                "source": "home_assistant",
                "entity_id": "camera.front_door",
                "name": "Front door camera",
                "room": "Front Porch",
                "aliases": ["Doorbell"],
            },
            {
                "source": "home_assistant",
                "entity_id": "camera.backyard",
                "name": "Backyard camera",
                "room": "Backyard",
                "aliases": [],
            },
            {
                "source": "native_satellite",
                "device_id": "sat-office",
                "name": "Office satellite",
                "room": "Office",
                "aliases": [],
            },
        ]

        selected, reason, _room = tater.TaterVisionTool._select_cameras(
            cameras, "What is by the doorbell?", "", "management-panel"
        )
        self.assertEqual(reason, "named_camera")
        self.assertEqual(selected[0]["entity_id"], "camera.front_door")

        selected, reason, room = tater.TaterVisionTool._select_cameras(
            cameras, "Is the dog out back?", "", "management-panel"
        )
        self.assertEqual((reason, room), ("semantic_area", "Back"))
        self.assertEqual(selected[0]["entity_id"], "camera.backyard")

        selected, reason, room = tater.TaterVisionTool._select_cameras(
            cameras, "What is this?", "Office", "sat-office"
        )
        self.assertEqual((reason, room), ("asking_room", "Office"))
        self.assertEqual(selected[0]["device_id"], "sat-office")
        self.assertIsNone(
            tater.TaterVisionTool._semantic_outdoor_area(
                "How do I look in this jacket for outside?"
            )
        )

    async def test_tater_vision_uses_existing_vision_callback_without_retaining_image(self) -> None:
        runtime = SimpleNamespace(room="Backyard")
        manager = SimpleNamespace(runtimes={"sat-1": runtime})
        descriptions = []

        async def describe(prompt, images):
            descriptions.append((prompt, images))
            return "The dog is resting near the patio door."

        tool = tater.TaterVisionTool(
            SimpleNamespace(), manager, lambda _entity_id: True, describe
        )
        tool.cameras = lambda: [
            {
                "source": "home_assistant",
                "entity_id": "camera.backyard",
                "name": "Backyard camera",
                "room": "Backyard",
                "aliases": [],
            }
        ]

        async def snapshot(_camera):
            return b"fresh image", "image/jpeg"

        tool._snapshot = snapshot
        result = await tool.async_call(
            {"query": "Is the dog outside?"},
            None,
            request="Is the dog outside?",
            device_id="sat-1",
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["facts"]["snapshot_bytes"], len(b"fresh image"))
        self.assertIn("dog", result["summary_for_user"])
        self.assertTrue(descriptions[0][1][0]["data_url"].startswith("data:image/jpeg"))
        self.assertNotIn("data:image", json.dumps(result))

    async def test_hydra_routes_current_camera_question_through_tater_vision(self) -> None:
        manager = _Manager()
        runtime = tater.MiniTaterRuntime(manager)
        runtime.setup()
        vision = _Vision()
        runtime.vision = vision
        responses = [
            {
                "role": "assistant",
                "content": json.dumps(
                    {
                        "mode": "execute",
                        "goal": "Check the backyard camera",
                        "response": "",
                        "steps": [
                            {
                                "id": "look-backyard",
                                "intent": "See whether the dog is outside",
                                "nl": "Is the dog in the backyard?",
                                "tool_hint": "tater_vision",
                            }
                        ],
                    }
                ),
            },
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "function": {
                            "name": "tater_vision",
                            "arguments": '{"query":"Is the dog in the backyard?"}',
                        }
                    }
                ],
            },
            {
                "role": "assistant",
                "content": "The dog is resting by the back door.",
            },
        ]

        async def fake_chat(_messages, **kwargs):
            if kwargs.get("role") == "thanatos":
                self.assertEqual(
                    kwargs["native_tools"][0]["function"]["name"],
                    "tater_vision",
                )
            return responses.pop(0)

        runtime._chat = fake_chat
        result = await runtime.async_process_text(
            "Is the dog in the backyard?",
            conversation_id="vision-tool-test",
            device_id="sat-1",
        )

        self.assertEqual(result["response"], "The dog is resting by the back door.")
        self.assertEqual(
            vision.calls[0],
            (
                {"query": "Is the dog in the backyard?"},
                None,
                "Is the dog in the backyard?",
                "sat-1",
            ),
        )
        ledger = manager.data["tater_hydra_ledger"][-1]
        self.assertEqual(ledger["tools"][0]["name"], "tater_vision")
        self.assertNotIn("data:image", json.dumps(ledger))

    async def test_three_heads_complete_compound_device_request_and_record_the_ledger(self) -> None:
        manager = _Manager()
        runtime = tater.MiniTaterRuntime(manager)
        runtime.setup()
        home = _Home()
        runtime.home = home
        responses = [
            {
                "role": "assistant",
                "content": json.dumps(
                    {
                        "mode": "execute",
                        "goal": "Turn on both requested devices",
                        "response": "",
                        "steps": [
                            {
                                "id": "kitchen",
                                "intent": "Turn on the kitchen light",
                                "nl": "Turn on the kitchen light",
                                "tool_hint": "device_control",
                            },
                            {
                                "id": "bedroom",
                                "intent": "Turn on the bedroom fan",
                                "nl": "Turn on the bedroom fan",
                                "tool_hint": "device_control",
                            },
                        ],
                    }
                ),
            },
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call-1",
                        "type": "function",
                        "function": {
                            "name": "device_control",
                            "arguments": '{"query":"Turn on the kitchen light"}',
                        },
                    }
                ],
            },
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call-2",
                        "type": "function",
                        "function": {
                            "name": "device_control",
                            "arguments": '{"query":"Turn on the bedroom fan"}',
                        },
                    }
                ],
            },
            {
                "role": "assistant",
                "content": "The kitchen light and bedroom fan are on.",
            },
        ]
        roles = []

        async def fake_chat(
            messages,
            *,
            tools=True,
            role="hermes",
            tool_choice="auto",
            native_tools=None,
        ):
            roles.append((role, tools, tool_choice))
            if tools and native_tools is None:
                definition = runtime.home.definition()
                self.assertEqual(definition["function"]["name"], "device_control")
            return responses.pop(0)

        runtime._chat = fake_chat
        result = await runtime.async_process_text(
            "Turn on the kitchen light and the bedroom fan",
            conversation_id="conversation-1",
            device_id="satellite-1",
        )

        self.assertEqual(result["response"], "The kitchen light and bedroom fan are on.")
        self.assertEqual(len(home.calls), 2)
        self.assertEqual(home.calls[0][0], {"query": "Turn on the kitchen light"})
        self.assertEqual(home.calls[1][0], {"query": "Turn on the bedroom fan"})
        self.assertEqual(
            [item[0] for item in roles],
            ["astraeus", "thanatos", "thanatos", "hermes"],
        )
        ledger = manager.data["tater_hydra_ledger"]
        self.assertEqual(ledger[-1]["outcome"], "done")
        self.assertEqual(len(ledger[-1]["plan"]["steps"]), 2)
        self.assertEqual(len(ledger[-1]["tools"]), 2)
        self.assertTrue(all(row["head"] == "thanatos" for row in ledger[-1]["tools"]))
        self.assertGreater(manager.saved, 0)

    async def test_follow_up_context_does_not_pose_hermes_reply_as_astraeus_output(self) -> None:
        manager = _Manager()
        runtime = tater.MiniTaterRuntime(manager)
        runtime.setup()
        runtime.home = _Home()
        planner_requests = []
        hermes_responses = iter(["The office light is on.", "It is still on."])

        async def fake_chat(messages, *, role="hermes", **_kwargs):
            if role == "astraeus":
                self.assertEqual([row["role"] for row in messages], ["system", "user"])
                envelope = json.loads(messages[-1]["content"])
                planner_requests.append(envelope)
                return {
                    "role": "assistant",
                    "content": json.dumps(
                        {
                            "mode": "chat",
                            "goal": "Answer the user",
                            "response": "",
                            "steps": [],
                        }
                    ),
                }
            return {"role": "assistant", "content": next(hermes_responses)}

        runtime._chat = fake_chat
        await runtime.async_process_text(
            "Is the office light on?",
            conversation_id="panel-follow-up",
            device_id="management-panel",
        )
        result = await runtime.async_process_text(
            "What about now?",
            conversation_id="panel-follow-up",
            device_id="management-panel",
        )

        self.assertEqual(result["response"], "It is still on.")
        self.assertEqual(planner_requests[0]["conversation"], [])
        self.assertEqual(
            planner_requests[1]["conversation"],
            [
                {"role": "user", "content": "Is the office light on?"},
                {"role": "assistant", "content": "The office light is on."},
            ],
        )
        self.assertEqual(planner_requests[1]["request"], "What about now?")

    async def test_thanatos_repairs_a_broadened_natural_language_tool_call_once(self) -> None:
        runtime = tater.MiniTaterRuntime(_Manager())
        runtime.setup()
        home = _Home()
        runtime.home = home
        responses = iter(
            [
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "function": {
                                "name": "device_control",
                                "arguments": '{"query":"turn on all lights"}',
                            }
                        }
                    ],
                },
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "function": {
                                "name": "device_control",
                                "arguments": '{"query":"Turn on the kitchen light"}',
                            }
                        }
                    ],
                },
            ]
        )
        calls = []

        async def fake_chat(messages, **_kwargs):
            calls.append(messages)
            return next(responses)

        runtime._chat = fake_chat
        result = await runtime._run_thanatos_step(
            user_text="Turn on the kitchen light",
            step={
                "id": "kitchen",
                "intent": "Turn on the kitchen light",
                "nl": "Turn on the kitchen light",
                "tool_hint": "device_control",
            },
            previous_results=[],
            context=None,
        )

        self.assertTrue(result["ok"])
        self.assertEqual(len(calls), 2)
        self.assertIn("Repair the previous call", calls[1][0]["content"])
        self.assertEqual(home.calls[0][0], {"query": "Turn on the kitchen light"})

    async def test_astraeus_reads_tater_style_native_structured_output(self) -> None:
        runtime = tater.MiniTaterRuntime(_Manager())
        runtime.setup()

        async def fake_chat(_messages, **kwargs):
            self.assertEqual(
                kwargs["native_tools"][0]["function"]["name"],
                "submit_hydra_plan",
            )
            return {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "function": {
                            "name": "submit_hydra_plan",
                            "arguments": '{"mode":"chat","goal":"Reply","response":"Hi","steps":[]}',
                        }
                    }
                ],
            }

        runtime._chat = fake_chat
        value = await runtime._structured_head_json(
            [{"role": "system", "content": "Plan"}],
            role="astraeus",
            function_name="submit_hydra_plan",
            description="Submit a plan",
            schema={"type": "object", "properties": {}},
            label="Astraeus",
        )

        self.assertEqual(value["mode"], "chat")
        self.assertEqual(value["response"], "Hi")

    async def test_second_plan_check_repairs_a_missing_compound_action(self) -> None:
        manager = _Manager()
        manager.data["tater_settings"]["hydra_astraeus_plan_review_enabled"] = True
        runtime = tater.MiniTaterRuntime(manager)
        runtime.setup()
        home = _Home()
        runtime.home = home

        def plan(queries):
            return {
                "role": "assistant",
                "content": json.dumps(
                    {
                        "mode": "execute",
                        "goal": "Complete the compound request",
                        "steps": [
                            {
                                "id": f"step-{index}",
                                "intent": query,
                                "nl": query,
                                "tool_hint": "device_control",
                            }
                            for index, query in enumerate(queries, start=1)
                        ],
                    }
                ),
            }

        def tool_call(call_id, query):
            return {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": call_id,
                        "type": "function",
                        "function": {
                            "name": "device_control",
                            "arguments": json.dumps({"query": query}),
                        },
                    }
                ],
            }

        responses = [
            plan(["Turn on the kitchen light"]),
            {"role": "assistant", "content": '{"approved":false,"reason":"Bedroom fan is missing"}'},
            plan(["Turn on the kitchen light", "Turn on the bedroom fan"]),
            {"role": "assistant", "content": '{"approved":true,"reason":"Complete"}'},
            tool_call("call-1", "Turn on the kitchen light"),
            tool_call("call-2", "Turn on the bedroom fan"),
            {"role": "assistant", "content": "Both devices are on."},
        ]

        async def fake_chat(_messages, **_kwargs):
            return responses.pop(0)

        runtime._chat = fake_chat
        result = await runtime.async_process_text(
            "Turn on the kitchen light and bedroom fan",
            conversation_id="repair-plan",
        )

        self.assertEqual(result["response"], "Both devices are on.")
        self.assertEqual(len(home.calls), 2)
        ledger = manager.data["tater_hydra_ledger"][-1]
        self.assertTrue(ledger["plan_review"]["approved"])
        self.assertEqual(len(ledger["plan"]["steps"]), 2)

    def test_beast_mode_routes_each_head_to_base_or_dedicated_model(self) -> None:
        manager = _Manager()
        manager.data["tater_settings"].update(
            {
                "hydra_beast_mode_enabled": True,
                "hydra_llm_astraeus_provider": "openai_compatible",
                "hydra_llm_astraeus_host": "http://planner.local/v1",
                "hydra_llm_astraeus_model": "planner-model",
                "hydra_llm_astraeus_api_key": "planner-secret",
                "hydra_llm_thanatos_provider": "base",
                "hydra_llm_hermes_provider": "openai_compatible",
                "hydra_llm_hermes_host": "http://writer.local/v1",
                "hydra_llm_hermes_model": "writer-model",
            }
        )
        runtime = tater.MiniTaterRuntime(manager)
        runtime.setup()

        self.assertEqual(runtime._role_model_settings("astraeus")["model"], "planner-model")
        self.assertTrue(runtime._role_model_settings("astraeus")["dedicated"])
        self.assertEqual(runtime._role_model_settings("thanatos")["model"], "test-model")
        self.assertFalse(runtime._role_model_settings("thanatos")["dedicated"])
        self.assertEqual(runtime._role_model_settings("hermes")["model"], "writer-model")
        public = tater.public_tater_settings(runtime.settings())
        self.assertNotIn("hydra_llm_astraeus_api_key", public)
        self.assertTrue(public["hydra_llm_astraeus_api_key_set"])

    async def test_vision_uses_base_or_dedicated_openai_compatible_route(self) -> None:
        manager = _Manager()
        runtime = tater.MiniTaterRuntime(manager)
        runtime.setup()
        data_url = "data:image/jpeg;base64," + base64.b64encode(b"photo").decode()
        images = tater.normalize_vision_images(
            [{"name": "room.jpg", "data_url": data_url}]
        )
        requests = []

        async def fake_post(url, api_key, payload):
            requests.append((url, api_key, payload))
            return {"choices": [{"message": {"content": "A lamp is on."}}]}

        runtime._post_json = fake_post
        observation = await runtime._describe_images("What is on?", images)
        self.assertEqual(observation, "A lamp is on.")
        self.assertEqual(requests[-1][0], "https://api.openai.com/v1/chat/completions")
        self.assertEqual(requests[-1][1], "secret")
        self.assertEqual(requests[-1][2]["model"], "test-model")
        self.assertEqual(
            requests[-1][2]["messages"][0]["content"][1]["image_url"]["url"],
            data_url,
        )

        manager.data["tater_settings"].update(
            {
                "vision_provider": "openai_compatible",
                "vision_base_url": "http://vision.local/v1",
                "vision_model": "dedicated-vision",
                "vision_api_key": "vision-key",
            }
        )
        await runtime._describe_images("What is on?", images)
        self.assertEqual(requests[-1][0], "http://vision.local/v1/chat/completions")
        self.assertEqual(requests[-1][1], "vision-key")
        self.assertEqual(requests[-1][2]["model"], "dedicated-vision")

    async def test_image_turn_feeds_visual_context_to_hydra_without_storing_image_data(self) -> None:
        manager = _Manager()
        runtime = tater.MiniTaterRuntime(manager)
        runtime.setup()
        planner_requests = []

        async def fake_describe(_user_text, _images):
            return "The image shows a blue mug on the counter."

        async def fake_chat(messages, *, role="hermes", **_kwargs):
            if role == "astraeus":
                envelope = json.loads(messages[-1]["content"])
                planner_requests.append(envelope)
                return {
                    "role": "assistant",
                    "content": json.dumps(
                        {
                            "mode": "chat",
                            "goal": "Answer the image question",
                            "response": "",
                            "steps": [],
                        }
                    ),
                }
            return {"role": "assistant", "content": "That is a blue mug."}

        runtime._describe_images = fake_describe
        runtime._chat = fake_chat
        data_url = "data:image/png;base64," + base64.b64encode(b"picture").decode()
        result = await runtime.async_process_text(
            "What color is the mug?",
            conversation_id="vision-chat",
            device_id="management-panel",
            images=[{"name": "counter.png", "data_url": data_url}],
        )

        self.assertEqual(result["response"], "That is a blue mug.")
        self.assertIn("blue mug", planner_requests[0]["request"])
        stored = manager.data["tater_conversations"]["vision-chat"][0]
        self.assertEqual(stored["content"], "What color is the mug?")
        self.assertEqual(stored["attachments"][0]["name"], "counter.png")
        self.assertNotIn("data_url", stored["attachments"][0])
        self.assertEqual(
            stored["vision_context"],
            "The image shows a blue mug on the counter.",
        )
        ledger = manager.data["tater_hydra_ledger"][-1]
        self.assertEqual(ledger["vision"]["provider"], "base")
        self.assertEqual(ledger["vision"]["image_count"], 1)

    def test_voice_entity_has_separate_home_assistant_and_tater_paths(self) -> None:
        source = (ROOT / "custom_components/tater_satellite/assist_satellite.py").read_text()
        self.assertIn('== "tater"', source)
        self.assertIn("async_run_voice(", source)
        self.assertIn("async_accept_pipeline_from_satellite(", source)

    def test_vad_sensitivity_entity_is_removed_from_the_ui(self) -> None:
        source = (ROOT / "custom_components/tater_satellite/select.py").read_text()

        self.assertNotIn("class TaterVadSelect", source)
        self.assertIn('f"{runtime.device_id}_vad_sensitivity"', source)

    async def test_tater_vad_closes_capture_after_trailing_silence(self) -> None:
        runtime = tater.MiniTaterRuntime(_Manager())
        events = []
        chunks = (
            [self._pcm_chunk(80)] * 10
            + [self._pcm_chunk(3200)] * 15
            + [self._pcm_chunk(70)] * 80
        )

        async def event_callback(name, data):
            events.append((name, data))

        with patch.object(
            tater, "_create_vad_backend", return_value=self._TestVad()
        ):
            captured = [
                chunk
                async for chunk in runtime._voice_activity_stream(
                    self._audio_stream(chunks),
                    {"rate": 16000, "width": 2, "channels": 1},
                    "default",
                    event_callback,
                )
            ]

        self.assertEqual(
            [name for name, _data in events],
            ["STT_VAD_START", "STT_VAD_END"],
        )
        self.assertIn(self._pcm_chunk(3200), captured)
        self.assertLess(len(captured), len(chunks))

    async def test_tater_vad_ends_a_no_speech_capture(self) -> None:
        runtime = tater.MiniTaterRuntime(_Manager())
        events = []
        chunks = [self._pcm_chunk(40)] * 500

        async def event_callback(name, data):
            events.append((name, data))

        with patch.object(
            tater, "_create_vad_backend", return_value=self._TestVad()
        ):
            with self.assertRaisesRegex(RuntimeError, "No speech"):
                async for _chunk in runtime._voice_activity_stream(
                    self._audio_stream(chunks),
                    {"rate": 16000, "width": 2, "channels": 1},
                    "default",
                    event_callback,
                ):
                    pass

        self.assertEqual([name for name, _data in events], ["STT_VAD_END"])

    async def test_tater_voice_turn_runs_after_server_vad(self) -> None:
        runtime = tater.MiniTaterRuntime(_Manager())
        events = []
        chunks = (
            [self._pcm_chunk(60)] * 5
            + [self._pcm_chunk(2800)] * 15
            + [self._pcm_chunk(50)] * 80
        )

        async def fake_transcribe(audio_stream, _audio_format):
            self.assertGreater(len([chunk async for chunk in audio_stream]), 0)
            return "Turn on the kitchen light"

        async def fake_process(_text, **_kwargs):
            return {
                "response": "The kitchen light is on.",
                "conversation_id": "conversation-1",
                "continue_conversation": False,
            }

        async def fake_synthesize(_text):
            return "audio/wav", b"wave"

        async def event_callback(name, data):
            events.append((name, data))

        runtime.async_transcribe = fake_transcribe
        runtime.async_process_text = fake_process
        runtime.async_synthesize = fake_synthesize
        satellite = SimpleNamespace(
            record={"vad_sensitivity": "default"},
            device_id="satellite-1",
            server_base_url="http://ha.test:8123",
        )

        with patch.object(
            tater, "_create_vad_backend", return_value=self._TestVad()
        ):
            await runtime.async_run_voice(
                satellite,
                self._audio_stream(chunks),
                {"rate": 16000, "width": 2, "channels": 1},
                "conversation-1",
                event_callback,
            )

        self.assertEqual(
            [name for name, _data in events],
            [
                "RUN_START",
                "STT_START",
                "STT_VAD_START",
                "STT_VAD_END",
                "STT_END",
                "INTENT_START",
                "INTENT_END",
                "TTS_START",
                "TTS_END",
                "RUN_END",
            ],
        )

    async def test_tater_vad_caps_a_continuous_voice_stream(self) -> None:
        runtime = tater.MiniTaterRuntime(_Manager())
        events = []
        chunks = [self._pcm_chunk(2600)] * 600

        async def event_callback(name, data):
            events.append((name, data))

        with patch.object(
            tater, "_create_vad_backend", return_value=self._TestVad()
        ):
            captured = [
                chunk
                async for chunk in runtime._voice_activity_stream(
                    self._audio_stream(chunks),
                    {"rate": 16000, "width": 2, "channels": 1},
                    "relaxed",
                    event_callback,
                )
            ]

        self.assertEqual(
            [name for name, _data in events],
            ["STT_VAD_START", "STT_VAD_END"],
        )
        self.assertLess(len(captured), len(chunks))


if __name__ == "__main__":
    unittest.main()
