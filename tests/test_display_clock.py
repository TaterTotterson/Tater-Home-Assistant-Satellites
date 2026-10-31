from __future__ import annotations

from datetime import UTC, datetime
import importlib.util
from pathlib import Path
import unittest
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
DISPLAY_CLOCK_PATH = (
    ROOT / "custom_components" / "tater_satellite" / "display_clock.py"
)
SPEC = importlib.util.spec_from_file_location(
    "tater_satellite_display_clock", DISPLAY_CLOCK_PATH
)
assert SPEC is not None and SPEC.loader is not None
display_clock = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(display_clock)


class DisplayClockTests(unittest.TestCase):
    def test_only_screen_weather_firmware_receives_clock(self) -> None:
        self.assertTrue(
            display_clock.supports_display_clock(
                {"screen": True, "screen_weather": True}
            )
        )
        self.assertFalse(display_clock.supports_display_clock({"screen": True}))
        self.assertFalse(display_clock.supports_display_clock({}))
        self.assertFalse(display_clock.supports_display_clock(None))

    def test_payload_carries_clock_and_daylight_offset(self) -> None:
        now = datetime(2026, 10, 27, 1, 48, tzinfo=UTC)
        payload = display_clock.display_clock_payload(
            now, ZoneInfo("America/Los_Angeles"), "America/Los_Angeles"
        )
        self.assertEqual(
            payload,
            {
                "available": False,
                "clock_unix_ms": int(now.timestamp() * 1000),
                "utc_offset_seconds": -7 * 60 * 60,
                "timezone": "America/Los_Angeles",
            },
        )

    def test_offset_follows_standard_time_change(self) -> None:
        payload = display_clock.display_clock_payload(
            datetime(2026, 11, 2, 1, 48, tzinfo=UTC),
            ZoneInfo("America/Los_Angeles"),
            "America/Los_Angeles",
        )
        self.assertEqual(payload["utc_offset_seconds"], -8 * 60 * 60)

    def test_utc_and_half_hour_zones(self) -> None:
        now = datetime(2026, 10, 27, 1, 48, tzinfo=UTC)
        self.assertEqual(
            display_clock.display_clock_payload(now, UTC, "UTC")[
                "utc_offset_seconds"
            ],
            0,
        )
        self.assertEqual(
            display_clock.display_clock_payload(
                now, ZoneInfo("America/St_Johns"), "America/St_Johns"
            )["utc_offset_seconds"],
            -int(2.5 * 60 * 60),
        )


if __name__ == "__main__":
    unittest.main()
