from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SETTINGS_PATH = ROOT / "custom_components" / "tater_satellite" / "settings.py"
SPEC = importlib.util.spec_from_file_location("tater_satellite_volume_settings", SETTINGS_PATH)
assert SPEC is not None and SPEC.loader is not None
settings = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(settings)


class VolumeControlTests(unittest.TestCase):
    def test_volume_is_normalized_and_sent_to_firmware(self) -> None:
        loud = settings.normalize_settings({"volume_percent": 140})
        quiet = settings.normalize_settings({"volume_percent": -10})

        self.assertEqual(loud["volume_percent"], 100)
        self.assertEqual(quiet["volume_percent"], 0)
        self.assertEqual(
            settings.firmware_payload(loud, board="voice-pe")["volume_percent"],
            100,
        )

    def test_volume_stays_out_of_the_full_settings_editor(self) -> None:
        editor_keys = {
            field["key"]
            for section in settings.SETTINGS_SCHEMA
            for field in section.get("fields", [])
        }

        self.assertNotIn("volume_percent", editor_keys)

    def test_panel_card_and_home_assistant_entity_use_the_same_setting(self) -> None:
        panel = (
            ROOT
            / "custom_components"
            / "tater_satellite"
            / "frontend"
            / "tater-satellite-panel.js"
        ).read_text(encoding="utf-8")
        numbers = (
            ROOT / "custom_components" / "tater_satellite" / "number.py"
        ).read_text(encoding="utf-8")
        manager = (
            ROOT / "custom_components" / "tater_satellite" / "manager.py"
        ).read_text(encoding="utf-8")

        self.assertIn("${this.renderDeviceVolume(device)}", panel)
        self.assertIn('settings: { volume_percent: volume }', panel)
        self.assertIn('data-device-volume="${escapeHtml(device.device_id)}"', panel)
        self.assertIn('"volume_percent",', numbers)
        self.assertIn('"mdi:volume-high",', numbers)
        self.assertIn("def _adopt_reported_device_volume(", manager)
        self.assertIn('overrides["volume_percent"] = volume', manager)
        self.assertIn("self.store.async_delay_save(lambda: self.data, 1.0)", manager)

    def test_manifest_version_is_bumped(self) -> None:
        manifest = json.loads(
            (
                ROOT
                / "custom_components"
                / "tater_satellite"
                / "manifest.json"
            ).read_text(encoding="utf-8")
        )

        self.assertEqual(manifest["version"], "0.3.8")


if __name__ == "__main__":
    unittest.main()
