from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
PAYLOADS_PATH = (
    ROOT / "custom_components" / "tater_satellite" / "display_payloads.py"
)
SPEC = importlib.util.spec_from_file_location(
    "tater_satellite_display_payloads", PAYLOADS_PATH
)
assert SPEC is not None and SPEC.loader is not None
payloads = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(payloads)

ECOBEE = {
    "hvac_modes": ["heat_cool", "heat", "cool", "off"],
    "current_temperature": 21.5,
    "temperature": 20,
    "current_humidity": 41,
    "min_temp": 7,
    "max_temp": 35,
    "target_temp_step": 0.5,
    "hvac_action": "heating",
    "supported_features": 1 | 2 | 8,
}


class ClimatePayloadTests(unittest.TestCase):
    def test_capability_gates(self) -> None:
        self.assertTrue(payloads.supports_display_climate({"screen_climate": True}))
        self.assertFalse(payloads.supports_display_climate({"screen": True}))
        self.assertTrue(payloads.supports_display_cameras({"screen_cameras": True}))
        self.assertFalse(payloads.supports_display_cameras(None))

    def test_thermostat_state_maps_to_screen_fields(self) -> None:
        payload = payloads.climate_payload(
            "climate.hallway",
            "heat",
            ECOBEE,
            room_name="Hallway",
            temperature_unit="°C",
        )
        self.assertEqual(
            payload,
            {
                "available": True,
                "room_id": "climate.hallway",
                "room_name": "Hallway",
                "temperature_unit": "C",
                "hvac_mode": "heat",
                "hvac_action": "heating",
                "available_hvac_modes": ["auto", "heat", "cool", "off"],
                "can_set_temperature": True,
                "can_set_mode": True,
                "current_temperature": 21.5,
                "target_temperature": 20.0,
                "current_humidity": 41.0,
                "minimum_temperature": 7.0,
                "maximum_temperature": 35.0,
                "temperature_step": 0.5,
            },
        )

    def test_heat_cool_reads_as_auto_and_maps_back(self) -> None:
        payload = payloads.climate_payload(
            "climate.hallway", "heat_cool", ECOBEE, room_name="", temperature_unit="°F"
        )
        self.assertEqual(payload["hvac_mode"], "auto")
        self.assertEqual(payload["temperature_unit"], "F")
        self.assertEqual(
            payloads.entity_hvac_mode("auto", ECOBEE["hvac_modes"]), "heat_cool"
        )
        self.assertEqual(payloads.entity_hvac_mode("heat", ECOBEE["hvac_modes"]), "heat")
        self.assertEqual(payloads.entity_hvac_mode("dry", ECOBEE["hvac_modes"]), "")
        # A thermostat with a real "auto" mode keeps it.
        self.assertEqual(payloads.entity_hvac_mode("auto", ["auto", "heat_cool"]), "auto")

    def test_range_only_thermostat_cannot_set_single_target(self) -> None:
        attributes = {**ECOBEE, "supported_features": 2, "temperature": None}
        payload = payloads.climate_payload(
            "climate.hallway", "heat_cool", attributes, room_name="", temperature_unit="°C"
        )
        self.assertFalse(payload["can_set_temperature"])
        self.assertNotIn("target_temperature", payload)

    def test_unavailable_thermostat_disables_panel(self) -> None:
        for state in ("unavailable", "unknown"):
            payload = payloads.climate_payload(
                "climate.hallway", state, ECOBEE, room_name="", temperature_unit="°C"
            )
            self.assertEqual(payload, {"available": False, "room_id": "climate.hallway"})
        self.assertEqual(payloads.unavailable_climate_payload(), {"available": False})


class RoomTemperatureTests(unittest.TestCase):
    def test_entity_list_keeps_unique_sensors_up_to_limit(self) -> None:
        value = " sensor.a, climate.x ,sensor.b,sensor.a,,sensor.c"
        self.assertEqual(
            payloads.parse_entity_list(value, "sensor", 2), ["sensor.a", "sensor.b"]
        )
        self.assertEqual(payloads.parse_entity_list(None, "sensor", 6), [])

    def test_room_row_uses_sensor_unit_and_skips_non_numeric(self) -> None:
        self.assertEqual(
            payloads.room_temperature_row(
                "sensor.den", "68.4", {"unit_of_measurement": "°F"}, room_name="Den"
            ),
            {
                "room_id": "sensor.den",
                "room_name": "Den",
                "temperature": 68.4,
                "temperature_unit": "F",
            },
        )
        self.assertEqual(
            payloads.room_temperature_row(
                "sensor.den", "20", {"unit_of_measurement": "°C"}, room_name="Den"
            )["temperature_unit"],
            "C",
        )
        for state in ("unavailable", "unknown", ""):
            self.assertIsNone(
                payloads.room_temperature_row("sensor.den", state, {}, room_name="Den")
            )


class CameraPayloadTests(unittest.TestCase):
    ROWS = [
        {"id": "camera.front_door", "name": "Front door", "room": "Porch", "available": True},
        {"id": "camera.garage", "name": "Garage", "room": "", "available": False},
        {"id": "", "name": "Broken"},
    ]

    def test_camera_list_without_selection(self) -> None:
        payload = payloads.cameras_payload(self.ROWS)
        self.assertTrue(payload["available"])
        self.assertFalse(payload["loading"])
        self.assertEqual([row["id"] for row in payload["cameras"]], ["camera.front_door", "camera.garage"])
        self.assertFalse(payload["cameras"][0]["talkback"])
        self.assertNotIn("selected_id", payload)

    def test_selected_camera_and_error(self) -> None:
        payload = payloads.cameras_payload(
            self.ROWS, selected_id="camera.front_door", loading=True, error="slow"
        )
        self.assertEqual(payload["selected_id"], "camera.front_door")
        self.assertEqual(payload["selected_name"], "Front door")
        self.assertEqual(payload["selected_room"], "Porch")
        self.assertTrue(payload["loading"])
        self.assertEqual(payload["error"], "slow")

    def test_no_cameras_is_unavailable(self) -> None:
        self.assertFalse(payloads.cameras_payload([])["available"])

    def test_frames_match_firmware_contract(self) -> None:
        jpeg = b"\xff\xd8\xff\xe0" + b"\x00" * 16
        self.assertEqual(payloads.camera_frame(jpeg), b"TCAM1" + jpeg)
        self.assertIsNone(payloads.camera_frame(b"\x89PNG\r\n\x1a\n"))
        self.assertIsNone(
            payloads.camera_frame(b"\xff\xd8" + b"\x00" * (4 * 1024 * 1024))
        )


if __name__ == "__main__":
    unittest.main()
