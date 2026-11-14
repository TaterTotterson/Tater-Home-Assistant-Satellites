from __future__ import annotations

import asyncio
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
                                "instruction": "Turn on the kitchen light",
                                "arguments": {
                                    "operation": "control",
                                    "command": "turn_on",
                                    "entity_ids": ["light.kitchen"],
                                },
                            },
                            {
                                "id": "bedroom",
                                "instruction": "Turn on the bedroom fan",
                                "arguments": {
                                    "operation": "control",
                                    "command": "turn_on",
                                    "entity_ids": ["fan.bedroom"],
                                },
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
                            "name": "control_home",
                            "arguments": '{"operation":"control","command":"turn_on","entity_ids":["light.kitchen"]}',
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
                            "name": "control_home",
                            "arguments": '{"operation":"control","command":"turn_on","entity_ids":["fan.bedroom"]}',
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

        async def fake_chat(messages, *, tools=True, role="hermes", tool_choice="auto"):
            roles.append((role, tools, tool_choice))
            if tools:
                definition = runtime.home.definition()
                self.assertEqual(definition["function"]["name"], "control_home")
            return responses.pop(0)

        runtime._chat = fake_chat
        result = await runtime.async_process_text(
            "Turn on the kitchen light and the bedroom fan",
            conversation_id="conversation-1",
            device_id="satellite-1",
        )

        self.assertEqual(result["response"], "The kitchen light and bedroom fan are on.")
        self.assertEqual(len(home.calls), 2)
        self.assertEqual(home.calls[0][0]["entity_ids"], ["light.kitchen"])
        self.assertEqual(home.calls[1][0]["entity_ids"], ["fan.bedroom"])
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

    async def test_second_plan_check_repairs_a_missing_compound_action(self) -> None:
        manager = _Manager()
        manager.data["tater_settings"]["hydra_astraeus_plan_review_enabled"] = True
        runtime = tater.MiniTaterRuntime(manager)
        runtime.setup()
        home = _Home()
        runtime.home = home

        def plan(entity_ids):
            return {
                "role": "assistant",
                "content": json.dumps(
                    {
                        "mode": "execute",
                        "goal": "Complete the compound request",
                        "steps": [
                            {
                                "id": f"step-{index}",
                                "instruction": f"Turn on {entity_id}",
                                "arguments": {
                                    "operation": "control",
                                    "command": "turn_on",
                                    "entity_ids": [entity_id],
                                },
                            }
                            for index, entity_id in enumerate(entity_ids, start=1)
                        ],
                    }
                ),
            }

        def tool_call(call_id, entity_id):
            return {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": call_id,
                        "type": "function",
                        "function": {
                            "name": "control_home",
                            "arguments": json.dumps(
                                {
                                    "operation": "control",
                                    "command": "turn_on",
                                    "entity_ids": [entity_id],
                                }
                            ),
                        },
                    }
                ],
            }

        responses = [
            plan(["light.kitchen"]),
            {"role": "assistant", "content": '{"approved":false,"reason":"Bedroom fan is missing"}'},
            plan(["light.kitchen", "fan.bedroom"]),
            {"role": "assistant", "content": '{"approved":true,"reason":"Complete"}'},
            tool_call("call-1", "light.kitchen"),
            tool_call("call-2", "fan.bedroom"),
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
