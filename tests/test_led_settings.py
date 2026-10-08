from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SETTINGS_PATH = ROOT / "custom_components" / "tater_satellite" / "settings.py"
SELECT_PATH = ROOT / "custom_components" / "tater_satellite" / "select.py"
MANAGER_PATH = ROOT / "custom_components" / "tater_satellite" / "manager.py"
PANEL_PATH = (
    ROOT
    / "custom_components"
    / "tater_satellite"
    / "frontend"
    / "tater-satellite-panel.js"
)
SPEC = importlib.util.spec_from_file_location("tater_satellite_led_settings", SETTINGS_PATH)
assert SPEC is not None and SPEC.loader is not None
settings = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(settings)


class LedSettingsTests(unittest.TestCase):
    def test_every_voice_stage_supports_no_animation(self) -> None:
        for key, options in (
            ("led_listening_animation", settings.LISTENING_ANIMATION_OPTIONS),
            ("led_thinking_animation", settings.THINKING_ANIMATION_OPTIONS),
            ("led_tool_call_animation", settings.TOOL_CALL_ANIMATION_OPTIONS),
            ("led_replying_animation", settings.REPLYING_ANIMATION_OPTIONS),
        ):
            self.assertEqual(options[0], {"value": "off", "label": "No Animation"})
            self.assertEqual(settings.normalize_settings({key: "off"})[key], "off")

    def test_music_animation_is_biscuit_only(self) -> None:
        expected = {
            "off",
            "audio_glow",
            "music_pulse",
            "music_bars",
            "music_orbit",
            "music_wave",
        }
        self.assertEqual(
            {row["value"] for row in settings.MUSIC_ANIMATION_OPTIONS}, expected
        )
        values = settings.normalize_settings({"led_music_animation": "music_wave"})
        self.assertEqual(
            settings.firmware_payload(values, board="biscuit")["led_music_animation"],
            "music_wave",
        )
        self.assertNotIn(
            "led_music_animation",
            settings.firmware_payload(values, board="voice-pe"),
        )

    def test_panel_and_entity_expose_music_animation_only_for_biscuit(self) -> None:
        led_section = next(
            row for row in settings.SETTINGS_SCHEMA if row["section"] == "led"
        )
        music = next(
            field
            for field in led_section["fields"]
            if field["key"] == "led_music_animation"
        )
        self.assertEqual(music["include_boards"], ["biscuit"])

        panel = PANEL_PATH.read_text(encoding="utf-8")
        selects = SELECT_PATH.read_text(encoding="utf-8")
        self.assertIn("field.include_boards", panel)
        self.assertIn('"led_music_animation"', selects)
        self.assertIn("board_supports_music_led_settings(runtime.board)", selects)

    def test_music_animation_is_sent_with_other_led_settings(self) -> None:
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
        led_group = next(group for group in groups if "led_brightness" in group)
        self.assertIn("led_music_animation", led_group)


if __name__ == "__main__":
    unittest.main()
