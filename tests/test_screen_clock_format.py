from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SETTINGS_PATH = ROOT / "custom_components" / "tater_satellite" / "settings.py"
SPEC = importlib.util.spec_from_file_location(
    "tater_satellite_screen_clock_format", SETTINGS_PATH
)
assert SPEC is not None and SPEC.loader is not None
settings = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(settings)


class ScreenClockFormatTests(unittest.TestCase):
    @staticmethod
    def capabilities() -> dict[str, object]:
        return {
            "screen": True,
            "screen_power_management_version": 1,
            "screen_clock_format": True,
        }

    def test_values_default_to_twelve_hour_and_accept_aliases(self) -> None:
        self.assertEqual(settings.normalize_settings({})["screen_clock_format"], "12h")
        for value, expected in {
            "24h": "24h",
            "24": "24h",
            " 12H ": "12h",
            "12": "12h",
            "military": "12h",
        }.items():
            self.assertEqual(
                settings.normalize_settings({"screen_clock_format": value})[
                    "screen_clock_format"
                ],
                expected,
                value,
            )

    def test_capable_echo_screens_receive_clock_format(self) -> None:
        values = settings.normalize_settings({"screen_clock_format": "24h"})
        for board in ("checkers", "crown", "athena", "rook"):
            payload = settings.firmware_payload(
                values, board=board, capabilities=self.capabilities()
            )
            self.assertEqual(payload["screen_clock_format"], "24h", board)

    def test_firmware_without_capability_never_receives_clock_format(self) -> None:
        values = settings.normalize_settings({"screen_clock_format": "24h"})
        older_echo = settings.firmware_payload(
            values,
            board="crown",
            capabilities={"screen": True, "screen_power_management_version": 1},
        )
        s3 = settings.firmware_payload(
            values, board="s3_box", capabilities=self.capabilities()
        )
        speaker = settings.firmware_payload(values, board="biscuit", capabilities={})
        self.assertNotIn("screen_clock_format", older_echo)
        self.assertIn("screen_brightness", older_echo)
        self.assertNotIn("screen_clock_format", s3)
        self.assertNotIn("screen_clock_format", speaker)

    def test_panel_field_is_capability_gated(self) -> None:
        section = next(
            row for row in settings.SETTINGS_SCHEMA if row["section"] == "display"
        )
        field = next(
            row for row in section["fields"] if row["key"] == "screen_clock_format"
        )
        self.assertEqual(field["required_capability"], "screen_clock_format")
        self.assertIn("s3_box", field["exclude_boards"])
        self.assertEqual(
            [option["value"] for option in field["options"]], ["12h", "24h"]
        )


if __name__ == "__main__":
    unittest.main()
