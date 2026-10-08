from __future__ import annotations

import ast
import importlib.util
import json
import unittest
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SETTINGS_PATH = ROOT / "custom_components" / "tater_satellite" / "settings.py"
MANAGER_PATH = ROOT / "custom_components" / "tater_satellite" / "manager.py"
HTTP_PATH = ROOT / "custom_components" / "tater_satellite" / "http.py"
ASSIST_PATH = ROOT / "custom_components" / "tater_satellite" / "assist_satellite.py"
PANEL_PATH = (
    ROOT
    / "custom_components"
    / "tater_satellite"
    / "frontend"
    / "tater-satellite-panel.js"
)

SPEC = importlib.util.spec_from_file_location(
    "tater_satellite_wake_family_settings", SETTINGS_PATH
)
assert SPEC is not None and SPEC.loader is not None
settings = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(settings)


def _settings_message_builder():
    """Load the framing helper without importing Home Assistant."""
    source = MANAGER_PATH.read_text(encoding="utf-8")
    module = ast.parse(source)
    selected: list[ast.stmt] = []
    for node in module.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name)
            and target.id in {"_MAX_DEVICE_TEXT_FRAME_BYTES", "_SETTINGS_WIRE_GROUPS"}
            for target in node.targets
        ):
            selected.append(node)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in {
            "_compact_json",
            "_settings_messages",
        }:
            selected.append(node)
    namespace: dict[str, Any] = {
        "Any": Any,
        "json": json,
        "wake_family_for": settings.wake_family_for,
        "envelope": lambda message_type, payload, include_metadata=False: {
            "v": 1,
            "type": message_type,
            "payload": payload,
        },
    }
    executable = compile(
        ast.Module(body=selected, type_ignores=[]),
        str(MANAGER_PATH),
        "exec",
    )
    exec(executable, namespace)
    return namespace["_settings_messages"], namespace["_compact_json"]


class WakeFamilySettingsTests(unittest.TestCase):
    def test_echo_family_uses_capabilities_with_board_fallback(self) -> None:
        self.assertEqual(
            settings.wake_family_for(
                capabilities={"openwakeword": True}, board="voice-pe"
            ),
            "echo",
        )
        self.assertEqual(settings.wake_family_for(board="checkers"), "echo")
        self.assertEqual(settings.wake_family_for(board="voice-pe"), "mww")

    def test_mww_family_forces_mww_and_strips_echo_only_settings(self) -> None:
        profile = settings.normalize_wake_family_settings(
            "mww",
            {
                "wake_detector_mode": "dual",
                "wake_word": "hey_tater",
                "oww_wake_word": "custom_url",
                "oww_wake_word_url": "https://example.test/hey.wake-bundle.json",
            },
        )
        payload = settings.firmware_payload(profile, board="voice-pe")

        self.assertEqual(profile["wake_detector_mode"], "mww")
        self.assertTrue(payload["wake_mww_enabled"])
        self.assertNotIn("wake_oww_enabled", payload)
        self.assertNotIn("oww_wake_word", payload)
        self.assertNotIn("oww_wake_word_url", payload)

    def test_echo_dual_mode_sends_both_detectors_and_one_paired_bundle(self) -> None:
        profile = settings.normalize_wake_family_settings(
            "echo",
            {
                "wake_detector_mode": "dual",
                "wake_word": "custom_url",
                "wake_word_url": "https://example.test/hey.json",
                "oww_wake_word": "custom_url",
                "oww_wake_word_url": "https://example.test/hey.wake-bundle.json",
            },
        )
        payload = settings.firmware_payload(
            profile,
            board="biscuit",
            capabilities={
                "openwakeword": True,
                "wake_detector_selection": True,
                "dual_wake_confirmation": True,
            },
        )

        self.assertTrue(payload["wake_mww_enabled"])
        self.assertTrue(payload["wake_oww_enabled"])
        self.assertEqual(payload["oww_wake_word"], "paired_bundle")
        self.assertEqual(
            payload["oww_wake_word_url"],
            "https://example.test/hey.wake-bundle.json",
        )

    def test_schema_separates_echo_mode_from_mww_model_selection(self) -> None:
        wake = next(
            section
            for section in settings.SETTINGS_SCHEMA
            if section.get("section") == "wake"
        )
        fields = {field["key"]: field for field in wake["fields"]}

        self.assertEqual(fields["wake_detector_mode"]["wake_families"], ["echo"])
        self.assertEqual(fields["wake_word"]["detector_modes"], ["mww"])
        self.assertEqual(fields["oww_wake_word"]["wake_families"], ["echo"])
        self.assertEqual(
            {row["value"] for row in fields["wake_detector_mode"]["options"]},
            {"mww", "oww", "dual"},
        )

    def test_manager_and_panel_route_profiles_by_satellite_family(self) -> None:
        manager = MANAGER_PATH.read_text(encoding="utf-8")
        http = HTTP_PATH.read_text(encoding="utf-8")
        assist = ASSIST_PATH.read_text(encoding="utf-8")
        panel = PANEL_PATH.read_text(encoding="utf-8")

        self.assertIn("def wake_family_settings(", manager)
        self.assertIn("wake_family_for(", manager)
        self.assertIn("async def async_set_wake_family_settings(", manager)
        self.assertIn("await self._async_wake_bundle(oww_url)", manager)
        self.assertIn('settings.get("oww_wake_word") if oww_only', manager)
        self.assertIn("class WakeFamilySettingsView", http)
        self.assertIn('settings/wake-family/{{family}}', http)
        self.assertIn("How should ESP firmware wake?", panel)
        self.assertIn("How should Echo firmware wake?", panel)
        self.assertIn("settings/wake-family/${family}", panel)
        self.assertIn("WAKE_FAMILY_SETTING_KEYS.forEach", panel)
        self.assertGreaterEqual(assist.count('"wake_detector_mode": "mww"'), 3)

    def test_dual_wake_settings_stay_below_legacy_wire_frame_limit(self) -> None:
        module = ast.parse(MANAGER_PATH.read_text(encoding="utf-8"))
        groups = None
        for node in module.body:
            if not isinstance(node, ast.Assign):
                continue
            if any(
                isinstance(target, ast.Name)
                and target.id == "_SETTINGS_WIRE_GROUPS"
                for target in node.targets
            ):
                groups = ast.literal_eval(node.value)
                break
        self.assertIsNotNone(groups)
        settings_payload = {
            "wake_engine": "micro_wake_word",
            "wake_mww_enabled": True,
            "wake_oww_enabled": True,
            "wake_word": "custom_url",
            "wake_word_url": "m" * 255,
            "wake_model_revision": "a" * 64,
            "oww_wake_word": "paired_bundle",
            "oww_wake_word_url": "o" * 255,
            "oww_model_revision": "b" * 64,
            "wake_sensitivity": "conservative",
            "wake_environment": "far_field",
            "wake_threshold": 0.99,
            "wake_sliding_window": 10,
        }
        for group in groups or ():
            payload = {
                key: settings_payload[key]
                for key in group
                if key in settings_payload
            }
            if not payload:
                continue
            frame = {"type": "settings", "payload": payload}
            self.assertLessEqual(
                len(json.dumps(frame, separators=(",", ":")).encode("utf-8")),
                1000,
            )

    def test_echo_receives_one_atomic_settings_snapshot_like_tater(self) -> None:
        build_messages, compact_json = _settings_message_builder()
        profile = settings.normalize_wake_family_settings(
            "echo",
            {
                "wake_detector_mode": "dual",
                "wake_word": "custom_url",
                "wake_word_url": "m" * 255,
                "wake_model_revision": "a" * 64,
                "oww_wake_word": "custom_url",
                "oww_wake_word_url": "o" * 255,
                "oww_model_revision": "b" * 64,
            },
        )
        payload = settings.firmware_payload(
            profile,
            board="biscuit",
            capabilities={"dual_wake_confirmation": True},
        )
        # Include enough ordinary live settings to exercise the path that
        # exceeds the legacy ESP receive window.
        payload.update(
            {
                "trainer_app_url": "http://trainer.local:8789",
                "wake_sound_url": "s" * 255,
                "led_listening_animation": "directional",
                "led_thinking_animation": "sparkle",
                "led_tool_call_animation": "ping_pong",
                "led_replying_animation": "voice_ring",
            }
        )

        messages = build_messages(
            payload,
            board="biscuit",
            capabilities={"dual_wake_confirmation": True},
        )

        self.assertGreater(len(compact_json(messages[0]).encode("utf-8")), 1000)
        self.assertEqual(len(messages), 1)
        sent = messages[0]["payload"]
        self.assertTrue(sent["wake_mww_enabled"])
        self.assertTrue(sent["wake_oww_enabled"])
        self.assertEqual(sent["wake_word"], "custom_url")
        self.assertEqual(sent["oww_wake_word"], "paired_bundle")

    def test_legacy_mww_family_still_fragments_large_settings(self) -> None:
        build_messages, compact_json = _settings_message_builder()
        payload = {
            "wake_engine": "micro_wake_word",
            "wake_mww_enabled": True,
            "wake_word": "custom_url",
            "wake_word_url": "m" * 255,
            "wake_model_revision": "a" * 64,
            "wake_sound_url": "s" * 255,
            "trainer_app_url": "t" * 255,
            "led_listening_animation": "directional",
            "led_thinking_animation": "sparkle",
            "led_tool_call_animation": "ping_pong",
            "led_replying_animation": "voice_ring",
        }

        messages = build_messages(payload, board="voice-pe", capabilities={})

        self.assertGreater(len(messages), 1)
        self.assertTrue(
            all(
                len(compact_json(message).encode("utf-8")) <= 1000
                for message in messages
            )
        )

    def test_bridge_surfaces_firmware_settings_failures(self) -> None:
        manager = MANAGER_PATH.read_text(encoding="utf-8")
        handler = manager.split('if kind == "settings.changed":', 1)[1].split(
            'if kind in {"log", "ota.status"}:', 1
        )[0]

        self.assertIn('runtime.settings_sync_state = "failed"', handler)
        self.assertIn('payload.get("error")', handler)
        self.assertIn('kind="settings.changed"', handler)


if __name__ == "__main__":
    unittest.main()
