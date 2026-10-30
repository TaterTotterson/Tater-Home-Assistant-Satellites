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

    def test_oww_mode_uses_oww_on_capable_firmware_and_mww_elsewhere(self) -> None:
        profile = settings.normalize_wake_family_settings(
            "echo",
            {
                "wake_detector_mode": "oww",
                "wake_word": "custom_url",
                "wake_word_url": "https://example.test/hey.json",
                "oww_wake_word": "custom_url",
                "oww_wake_word_url": "https://example.test/hey.wake-bundle.json",
            },
        )
        capable = settings.firmware_payload(
            profile,
            board="checkers",
            capabilities={"openwakeword": True},
        )
        mww_only = settings.firmware_payload(profile, board="voice-pe")

        self.assertEqual(profile["wake_detector_mode"], "oww")
        self.assertFalse(capable["wake_mww_enabled"])
        self.assertTrue(capable["wake_oww_enabled"])
        self.assertEqual(capable["oww_wake_word"], "paired_bundle")
        self.assertTrue(mww_only["wake_mww_enabled"])
        self.assertNotIn("wake_oww_enabled", mww_only)
        self.assertNotIn("oww_wake_word", mww_only)
        self.assertEqual(mww_only["wake_word_url"], "https://example.test/hey.json")

    def test_schema_presents_all_five_shared_wake_choices(self) -> None:
        wake = next(
            section
            for section in settings.SETTINGS_SCHEMA
            if section.get("section") == "wake"
        )
        fields = {field["key"]: field for field in wake["fields"]}

        self.assertNotIn("wake_families", fields["wake_engine"])
        self.assertEqual(
            fields["wake_engine"]["options"][0],
            {
                "value": "micro_wake_word",
                "label": "On-device wake detection",
            },
        )
        self.assertEqual(fields["wake_detector_mode"]["wake_families"], ["echo"])
        self.assertEqual(
            fields["wake_detector_mode"]["label"], "Wake detection mode"
        )
        self.assertEqual(fields["wake_word"]["detector_modes"], ["mww"])
        self.assertEqual(fields["oww_wake_word"]["label"], "Wake word bundle")
        self.assertEqual(fields["oww_wake_word"]["wake_families"], ["echo"])
        self.assertEqual(
            fields["oww_wake_word"]["detector_modes"],
            ["oww", "nww", "mww_oww", "mww_nww"],
        )
        self.assertEqual(
            fields["wake_detector_mode"]["options"],
            [
                {"value": "mww", "label": "MWW", "group": "single"},
                {"value": "oww", "label": "OWW", "group": "single"},
                {"value": "nww", "label": "NWW", "group": "single"},
                {"value": "mww_oww", "label": "MWW + OWW", "group": "dual"},
                {"value": "mww_nww", "label": "MWW + NWW", "group": "dual"},
            ],
        )
        self.assertEqual(fields["nww_architecture"]["detector_modes"], ["nww", "mww_nww"])
        self.assertEqual(fields["wake_sensitivity"]["scopes"], ["device"])
        self.assertEqual(fields["wake_environment"]["scopes"], ["device"])
        self.assertEqual(fields["mww_tuning_override_enabled"]["scopes"], ["wake"])

    def test_manager_and_panel_use_one_shared_wake_profile(self) -> None:
        manager = MANAGER_PATH.read_text(encoding="utf-8")
        http = HTTP_PATH.read_text(encoding="utf-8")
        assist = ASSIST_PATH.read_text(encoding="utf-8")
        panel = PANEL_PATH.read_text(encoding="utf-8")

        self.assertIn("def shared_wake_settings(", manager)
        self.assertIn("def wake_family_settings(", manager)
        self.assertIn("wake_family_for(", manager)
        self.assertIn("async def async_set_shared_wake_settings(", manager)
        self.assertIn("async def async_set_wake_family_settings(", manager)
        self.assertIn("parse_wake_bundle(", manager)
        self.assertIn('"nww" if mode in {"nww", "mww_nww"}', manager)
        self.assertNotIn('if mode == "oww":\n            mode = "dual"', manager)
        self.assertIn('families["echo"] = next_settings', manager)
        self.assertIn('families["mww"] = normalize_wake_family_settings(', manager)
        self.assertIn("class SharedWakeSettingsView", http)
        self.assertIn("class WakeFamilySettingsView", http)
        self.assertIn('settings/wake-family/{{family}}', http)
        self.assertIn("allow_catalog_only=True", http)
        self.assertIn("How should satellites wake?", panel)
        self.assertNotIn("How should ESP firmware wake?", panel)
        self.assertNotIn("How should Echo firmware wake?", panel)
        self.assertIn('"settings/wake"', panel)
        self.assertIn("this._wakeDraft", panel)
        self.assertIn("VOICE_DEFAULT_SETTING_KEYS", panel)
        self.assertIn("TRAINER_SETTING_KEYS", panel)
        self.assertIn("WAKE_VERIFIER_SETTING_KEYS", panel)
        self.assertIn('"settings/verifier"', panel)
        self.assertIn('"settings/trainer"', panel)
        self.assertIn("MWW + NWW", panel)
        self.assertIn("renderWakeTuningOverrides", panel)
        self.assertGreaterEqual(assist.count('"wake_detector_mode": "mww"'), 3)

    def test_global_forms_have_disjoint_explicit_allowlists(self) -> None:
        self.assertEqual(
            settings.WAKE_VERIFIER_SETTING_KEYS,
            {"wake_verifier_mode"},
        )
        self.assertEqual(
            settings.TRAINER_SETTING_KEYS,
            {
                "capture_wake_audio",
                "capture_close_misses",
                "close_miss_threshold",
                "trainer_app_url",
            },
        )
        groups = (
            settings.VOICE_DEFAULT_SETTING_KEYS,
            settings.TRAINER_SETTING_KEYS,
            settings.WAKE_VERIFIER_SETTING_KEYS,
            settings.SHARED_WAKE_MODEL_SETTING_KEYS,
        )
        for index, group in enumerate(groups):
            for other in groups[index + 1 :]:
                self.assertTrue(group.isdisjoint(other))

        manager = MANAGER_PATH.read_text(encoding="utf-8")
        self.assertIn("allowed_keys=VOICE_DEFAULT_SETTING_KEYS", manager)
        self.assertIn("allowed_keys=TRAINER_SETTING_KEYS", manager)
        self.assertIn("allowed_keys=WAKE_VERIFIER_SETTING_KEYS", manager)

    def test_oww_only_mode_is_preserved(self) -> None:
        profile = settings.normalize_wake_family_settings(
            "echo",
            {
                "wake_detector_mode": "oww",
                "wake_mww_enabled": False,
                "wake_oww_enabled": True,
            },
        )

        self.assertEqual(profile["wake_detector_mode"], "oww")
        self.assertFalse(profile["wake_mww_enabled"])
        self.assertTrue(profile["wake_oww_enabled"])
        self.assertFalse(profile["wake_nww_enabled"])

    def test_nww_modes_project_selected_architecture_and_fallback_to_mww(self) -> None:
        profile = settings.normalize_wake_family_settings(
            "echo",
            {
                "wake_detector_mode": "mww_nww",
                "wake_word": "custom_url",
                "wake_word_url": "https://example.test/hey.esphome.json",
                "oww_wake_word": "custom_url",
                "oww_wake_word_url": "https://example.test/hey.wake-bundle.json",
                "nww_model_revision": "c" * 64,
                "nww_architecture": "gru",
                "nww_gru_profile_threshold": 0.93,
                "nww_gru_profile_patience": 2,
            },
        )
        capable = settings.firmware_payload(
            profile,
            board="biscuit",
            capabilities={"nanowakeword": True},
        )
        old_firmware = settings.firmware_payload(
            profile,
            board="biscuit",
            capabilities={"openwakeword": True},
        )

        self.assertTrue(capable["wake_mww_enabled"])
        self.assertTrue(capable["wake_nww_enabled"])
        self.assertFalse(capable["wake_oww_enabled"])
        self.assertEqual(capable["nww_architecture"], "gru")
        self.assertEqual(capable["nww_threshold"], 0.93)
        self.assertEqual(capable["nww_patience"], 2)
        self.assertEqual(
            capable["nww_wake_word_url"],
            "https://example.test/hey.wake-bundle.json",
        )
        self.assertTrue(old_firmware["wake_mww_enabled"])
        self.assertNotIn("wake_nww_enabled", old_firmware)

    def test_model_tuning_is_shared_but_room_profile_remains_per_device(self) -> None:
        global_values = settings.normalize_settings({})
        family = settings.normalize_wake_family_settings(
            "echo",
            {
                "wake_detector_mode": "mww_oww",
                "mww_tuning_override_enabled": True,
                "mww_threshold_override": 0.91,
            },
        )
        merged = settings.merged_settings(
            global_values,
            {
                "wake_detector_mode": "nww",
                "mww_threshold_override": 0.2,
                "wake_sensitivity": "high",
                "wake_environment": "tv_nearby",
            },
            family,
        )

        self.assertEqual(merged["wake_detector_mode"], "mww_oww")
        self.assertEqual(merged["mww_threshold_override"], 0.91)
        self.assertEqual(merged["wake_sensitivity"], "high")
        self.assertEqual(merged["wake_environment"], "tv_nearby")

    def test_echo_mww_mode_does_not_send_openwakeword_settings(self) -> None:
        profile = settings.normalize_wake_family_settings(
            "echo",
            {
                "wake_detector_mode": "mww",
                "oww_wake_word": "custom_url",
                "oww_wake_word_url": "https://example.test/hey.wake-bundle.json",
            },
        )
        payload = settings.firmware_payload(
            profile,
            board="biscuit",
            capabilities={"dual_wake_confirmation": True},
        )

        self.assertTrue(payload["wake_mww_enabled"])
        self.assertFalse(payload["wake_oww_enabled"])
        self.assertNotIn("oww_wake_word", payload)
        self.assertNotIn("oww_wake_word_url", payload)

    def test_panel_live_refresh_preserves_active_editor_controls(self) -> None:
        panel = PANEL_PATH.read_text(encoding="utf-8")

        self.assertIn("this._backgroundRenderPending = false", panel)
        self.assertIn("hasActiveInput()", panel)
        self.assertIn("this.shadowRoot?.activeElement", panel)
        self.assertIn("document.hidden || this.hasActiveInput()", panel)
        self.assertIn("this._backgroundRenderPending = true", panel)
        self.assertIn("!background || !this.hasActiveInput()", panel)

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
