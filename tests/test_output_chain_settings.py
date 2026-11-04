from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SETTINGS_PATH = ROOT / "custom_components" / "tater_satellite" / "settings.py"
SPEC = importlib.util.spec_from_file_location(
    "tater_satellite_output_chain", SETTINGS_PATH
)
assert SPEC is not None and SPEC.loader is not None
settings = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(settings)


class OutputChainSettingsTests(unittest.TestCase):
    CAPABLE = {"output_chain": True}

    def test_defaults_match_echo_firmware(self) -> None:
        values = settings.normalize_settings({})
        payload = settings.firmware_payload(
            values, board="radar", capabilities=self.CAPABLE
        )
        self.assertEqual(payload["eq_bands"], [0.0] * 8)
        self.assertIs(payload["eq_loudness"], False)
        self.assertIs(payload["bass_guard_enabled"], True)
        self.assertEqual(payload["bass_guard_db"], -30.0)
        self.assertIs(payload["limiter_enabled"], True)
        self.assertEqual(payload["limiter_threshold_db"], -1.0)
        self.assertEqual(payload["limiter_release_ms"], 150.0)

    def test_bands_are_sent_as_one_array_low_shelf_first(self) -> None:
        values = settings.normalize_settings(
            {"eq_band_125": "4", "eq_band_8k": -2.5, "bass_guard_db": -10}
        )
        for board in ("radar", "crown", "biscuit"):
            payload = settings.firmware_payload(
                values, board=board, capabilities=self.CAPABLE
            )
            self.assertEqual(
                payload["eq_bands"], [4.0, 0, 0, 0, 0, 0, 0, -2.5], board
            )
            self.assertEqual(payload["bass_guard_db"], -10.0, board)
            self.assertFalse(
                any(key.startswith("eq_band_") for key in payload), board
            )

    def test_values_are_clamped_to_firmware_ranges(self) -> None:
        # The firmware rejects the whole settings frame on an out-of-range
        # output value, so the integration must never send one.
        values = settings.normalize_settings(
            {
                "eq_band_250": 40,
                "eq_band_500": -40,
                "bass_guard_db": -200,
                "limiter_threshold_db": 3,
                "limiter_release_ms": 5,
                "bass_guard_enabled": "off",
            }
        )
        payload = settings.firmware_payload(
            values, board="radar", capabilities=self.CAPABLE
        )
        self.assertEqual(payload["eq_bands"][1:3], [12.0, -12.0])
        self.assertEqual(payload["bass_guard_db"], -60.0)
        self.assertEqual(payload["limiter_threshold_db"], 0.0)
        self.assertEqual(payload["limiter_release_ms"], 20.0)
        self.assertIs(payload["bass_guard_enabled"], False)

    def test_firmware_without_capability_never_receives_output_chain(self) -> None:
        values = settings.normalize_settings({"bass_guard_db": -10})
        for capabilities in ({}, {"output_chain": False}, {"output_chain": 1}):
            payload = settings.firmware_payload(
                values, board="radar", capabilities=capabilities
            )
            for key in settings.OUTPUT_CHAIN_SETTING_KEYS | {"eq_bands"}:
                self.assertNotIn(key, payload)
        esp = settings.firmware_payload(values, board="voice_pe", capabilities={})
        self.assertNotIn("bass_guard_db", esp)

    def test_panel_section_is_device_scoped_and_capability_gated(self) -> None:
        section = next(
            row for row in settings.SETTINGS_SCHEMA if row["section"] == "output_chain"
        )
        self.assertEqual(section["scopes"], ["device"])
        self.assertEqual(section["required_capability"], "output_chain")
        keys = [field["key"] for field in section["fields"]]
        self.assertEqual(set(keys), settings.OUTPUT_CHAIN_SETTING_KEYS)
        floor = next(f for f in section["fields"] if f["key"] == "bass_guard_db")
        self.assertEqual((floor["min"], floor["max"]), (-60, 0))
        self.assertEqual(
            floor["show_when"], {"key": "bass_guard_enabled", "equals": True}
        )


if __name__ == "__main__":
    unittest.main()
