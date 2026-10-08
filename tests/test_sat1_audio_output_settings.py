from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SETTINGS_PATH = ROOT / "custom_components" / "tater_satellite" / "settings.py"
SELECT_PATH = ROOT / "custom_components" / "tater_satellite" / "select.py"
MANAGER_PATH = ROOT / "custom_components" / "tater_satellite" / "manager.py"
SPEC = importlib.util.spec_from_file_location(
    "tater_satellite_audio_output_settings", SETTINGS_PATH
)
assert SPEC is not None and SPEC.loader is not None
settings = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(settings)


class Sat1AudioOutputSettingsTests(unittest.TestCase):
    def test_modes_are_normalized(self) -> None:
        for mode in ("auto", "internal", "aux", "both"):
            self.assertEqual(
                settings.normalize_settings({"audio_output_mode": mode})[
                    "audio_output_mode"
                ],
                mode,
            )
        self.assertEqual(
            settings.normalize_settings({"audio_output_mode": "invalid"})[
                "audio_output_mode"
            ],
            "auto",
        )

    def test_payload_is_only_sent_to_satellite1_boards(self) -> None:
        values = settings.normalize_settings({"audio_output_mode": "aux"})

        for board in (
            "satellite1",
            "satellite-1",
            "sat1",
            "satellite1-beta-rev41",
            "satellite1_beta_rev41",
        ):
            with self.subTest(board=board):
                self.assertEqual(
                    settings.firmware_payload(values, board=board)[
                        "audio_output_mode"
                    ],
                    "aux",
                )

        for board in ("voice-pe", "respeaker-xvf3800", "s3-box", "biscuit"):
            with self.subTest(board=board):
                self.assertNotIn(
                    "audio_output_mode",
                    settings.firmware_payload(values, board=board),
                )

    def test_panel_section_is_satellite1_device_only(self) -> None:
        section = next(
            row
            for row in settings.SETTINGS_SCHEMA
            if row["section"] == "audio_output"
        )
        self.assertEqual(section["scopes"], ["device"])
        self.assertIn("satellite1", section["include_boards"])
        self.assertIn("satellite1_beta_rev41", section["include_boards"])
        field = section["fields"][0]
        self.assertEqual(field["key"], "audio_output_mode")
        self.assertEqual(
            [option["value"] for option in field["options"]],
            ["auto", "internal", "aux", "both"],
        )

    def test_select_entity_is_satellite1_only(self) -> None:
        source = SELECT_PATH.read_text(encoding="utf-8")
        self.assertIn('"audio_output_mode"', source)
        self.assertIn("board_supports_audio_output_settings(runtime.board)", source)

    def test_output_mode_is_sent_with_audio_settings(self) -> None:
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
        audio_group = next(group for group in groups if "volume_percent" in group)
        self.assertIn("audio_output_mode", audio_group)


if __name__ == "__main__":
    unittest.main()
