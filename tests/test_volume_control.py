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
        volume_adoption = manager.split(
            "def _adopt_reported_device_volume(", 1
        )[1].split("\n    def ", 1)[0]

        self.assertIn("${this.renderDeviceVolume(device)}", panel)
        self.assertIn('settings: { volume_percent: volume }', panel)
        self.assertIn('data-device-volume="${escapeHtml(device.device_id)}"', panel)
        self.assertIn('"volume_percent",', numbers)
        self.assertIn('"mdi:volume-high",', numbers)
        self.assertIn("def _adopt_reported_device_volume(", manager)
        self.assertIn('_as_int(live.get("volume_percent"))', manager)
        self.assertNotIn('_as_int(live.get("volume_percent"), 80)', manager)
        self.assertIn('overrides["volume_percent"] = volume', manager)
        self.assertIn("self.store.async_delay_save(lambda: self.data, 1.0)", manager)
        self.assertIn('if kind == "settings.changed":', manager)
        self.assertIn("self._adopt_reported_device_volume(runtime, payload)", manager)
        self.assertIn('live = status.get("settings")', volume_adoption)

    def test_volume_entity_is_not_removed_during_setup(self) -> None:
        setup = (
            ROOT / "custom_components" / "tater_satellite" / "__init__.py"
        ).read_text(encoding="utf-8")

        self.assertNotIn('unique_id.endswith("_volume_percent")', setup)
        self.assertNotIn("registry.async_remove", setup)

    def test_volume_is_sent_with_the_audio_settings_group(self) -> None:
        manager = (
            ROOT / "custom_components" / "tater_satellite" / "manager.py"
        ).read_text(encoding="utf-8")
        audio_group = manager.split('_SETTINGS_WIRE_GROUPS = (', 1)[1].split(
            '    ),', 3
        )[2]

        self.assertIn('"volume_percent"', audio_group)

    def test_manifest_version_is_bumped(self) -> None:
        manifest = json.loads(
            (
                ROOT
                / "custom_components"
                / "tater_satellite"
                / "manifest.json"
            ).read_text(encoding="utf-8")
        )

        self.assertEqual(manifest["version"], "0.3.16")


if __name__ == "__main__":
    unittest.main()
