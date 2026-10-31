from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SETTINGS_PATH = ROOT / "custom_components" / "tater_satellite" / "settings.py"
SPEC = importlib.util.spec_from_file_location(
    "tater_satellite_screen_climate_setting", SETTINGS_PATH
)
assert SPEC is not None and SPEC.loader is not None
settings = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(settings)


class ScreenClimateSettingTests(unittest.TestCase):
    def test_entity_is_stored_as_text_and_defaults_to_none(self) -> None:
        self.assertEqual(settings.normalize_settings({})["screen_climate_entity"], "")
        self.assertEqual(
            settings.normalize_settings(
                {"screen_climate_entity": " climate.bedroom "}
            )["screen_climate_entity"],
            "climate.bedroom",
        )

    def test_entity_is_never_sent_to_firmware(self) -> None:
        values = settings.normalize_settings({"screen_climate_entity": "climate.bedroom"})
        payload = settings.firmware_payload(
            values,
            board="crown",
            capabilities={"screen_power_management_version": 1, "screen_climate": True},
        )
        self.assertNotIn("screen_climate_entity", payload)

    def test_room_temperature_checklist(self) -> None:
        self.assertEqual(
            settings.normalize_settings({})["screen_room_temperature_entities"], ""
        )
        values = settings.normalize_settings(
            {"screen_room_temperature_entities": "sensor.a,sensor.b"}
        )
        self.assertEqual(values["screen_room_temperature_entities"], "sensor.a,sensor.b")
        payload = settings.firmware_payload(
            values,
            board="crown",
            capabilities={"screen_power_management_version": 1, "screen_climate": True},
        )
        self.assertNotIn("screen_room_temperature_entities", payload)
        section = next(
            row for row in settings.SETTINGS_SCHEMA if row["section"] == "display"
        )
        field = next(
            row
            for row in section["fields"]
            if row["key"] == "screen_room_temperature_entities"
        )
        self.assertEqual(field["type"], "entity_list")
        self.assertEqual(field["max_items"], 6)
        self.assertEqual(field["required_capability"], "screen_climate")

    def test_dashboard_field_is_gated_on_climate_panel(self) -> None:
        section = next(
            row for row in settings.SETTINGS_SCHEMA if row["section"] == "display"
        )
        field = next(
            row for row in section["fields"] if row["key"] == "screen_climate_entity"
        )
        self.assertEqual(field["type"], "select")
        self.assertEqual(field["required_capability"], "screen_climate")
        self.assertIn("s3_box", field["exclude_boards"])
        self.assertEqual(field["options"], [{"value": "", "label": "None"}])


if __name__ == "__main__":
    unittest.main()
