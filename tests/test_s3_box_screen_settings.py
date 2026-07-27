from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "custom_components" / "tater_satellite" / "settings.py"
SPEC = importlib.util.spec_from_file_location("tater_satellite_settings", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
settings = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(settings)


class S3BoxScreenSettingsTests(unittest.TestCase):
    def test_values_are_normalized(self) -> None:
        values = settings.normalize_settings(
            {
                "screen_brightness": 140,
                "screen_night_mode_enabled": "yes",
                "screen_night_brightness": -5,
                "screen_night_start": "7:05",
                "screen_night_end": "not-a-time",
            }
        )

        self.assertEqual(values["screen_brightness"], 100)
        self.assertTrue(values["screen_night_mode_enabled"])
        self.assertEqual(values["screen_night_brightness"], 0)
        self.assertEqual(values["screen_night_start"], "07:05")
        self.assertEqual(values["screen_night_end"], "07:00")

    def test_screen_payload_is_only_sent_to_s3_box(self) -> None:
        values = settings.normalize_settings(
            {
                "screen_brightness": 65,
                "screen_night_mode_enabled": True,
                "screen_night_brightness": 4,
                "screen_night_start": "21:30",
                "screen_night_end": "06:45",
            }
        )

        s3_payload = settings.firmware_payload(
            values,
            board="s3-box",
            local_time_seconds=86399,
        )
        voicepe_payload = settings.firmware_payload(
            values,
            board="voice-pe",
            local_time_seconds=86399,
        )

        self.assertEqual(s3_payload["screen_brightness"], 65)
        self.assertEqual(s3_payload["screen_night_start"], "21:30")
        self.assertEqual(s3_payload["screen_local_time_seconds"], 86399)
        self.assertNotIn("screen_brightness", voicepe_payload)
        self.assertNotIn("screen_night_start", voicepe_payload)
        self.assertNotIn("screen_local_time_seconds", voicepe_payload)

    def test_panel_section_is_s3_device_only(self) -> None:
        section = next(
            row for row in settings.SETTINGS_SCHEMA if row["section"] == "display"
        )
        self.assertEqual(section["scopes"], ["device"])
        self.assertEqual(section["include_boards"], ["s3_box"])
        self.assertEqual(
            {field["key"] for field in section["fields"]},
            {
                "screen_brightness",
                "screen_night_mode_enabled",
                "screen_night_brightness",
                "screen_night_start",
                "screen_night_end",
            },
        )


if __name__ == "__main__":
    unittest.main()
