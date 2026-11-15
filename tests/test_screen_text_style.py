from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("text_style_settings", ROOT / "custom_components/tater_satellite/settings.py")
settings = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(settings)
CAPS = {"screen": True, "screen_power_management_version": 1, "screen_text_style": True}


class ScreenTextStyleTests(unittest.TestCase):
    def test_default_validation_and_partial_updates(self):
        self.assertEqual(settings.normalize_settings({})["screen_text_style"], "smooth")
        for value, expected in (("matrix", "matrix"), (" MATRIX ", "matrix"), (None, "smooth"), ("bad", "smooth"), ({}, "smooth")):
            self.assertEqual(settings.normalize_settings({"screen_text_style": value})["screen_text_style"], expected)
        current = settings.normalize_settings({"screen_text_style": "matrix"})
        self.assertEqual(settings.normalize_settings({"screen_brightness": 30}, base=current)["screen_text_style"], "matrix")

    def test_only_capable_echo_screens_receive_the_choice(self):
        values = settings.normalize_settings({"screen_text_style": "matrix"})
        for board in ("checkers", "cronos", "crown", "athena", "rook", "echo-show-5-2nd-gen"):
            self.assertEqual(settings.firmware_payload(values, board=board, capabilities=CAPS)["screen_text_style"], "matrix", board)
        for board, caps in (("athena", {}), ("biscuit", CAPS), ("voice-pe", CAPS), ("s3_box", CAPS), ("athena", {"screen_text_style": "true"})):
            self.assertNotIn("screen_text_style", settings.firmware_payload(values, board=board, capabilities=caps))

    def test_schema_is_per_device_capability_gated_and_in_the_display_wire_group(self):
        section = next(row for row in settings.SETTINGS_SCHEMA if row["section"] == "display")
        self.assertEqual(section["scopes"], ["device"])
        self.assertIn("cronos", section["include_boards"])
        field = next(row for row in section["fields"] if row["key"] == "screen_text_style")
        self.assertEqual(field["required_capability"], "screen_text_style")
        self.assertEqual([row["value"] for row in field["options"]], ["smooth", "matrix"])
        source = ast.parse((ROOT / "custom_components/tater_satellite/manager.py").read_text())
        groups = next(ast.literal_eval(node.value) for node in source.body if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "_SETTINGS_WIRE_GROUPS" for target in node.targets))
        self.assertIn("screen_text_style", next(group for group in groups if "screen_brightness" in group))
        self.assertNotIn("screen_text_style", settings.VOICE_DEFAULT_SETTING_KEYS)

    def test_per_device_overrides_do_not_change_voice_defaults_or_other_devices(self):
        defaults = settings.normalize_settings({})
        one = settings.merged_settings(defaults, {"screen_text_style": "matrix"})
        two = settings.merged_settings(defaults, {})
        self.assertEqual(one["screen_text_style"], "matrix")
        self.assertEqual(two["screen_text_style"], "smooth")
        self.assertEqual(defaults["screen_text_style"], "smooth")

    def test_accepted_local_choice_updates_only_its_own_record(self):
        source = ast.parse((ROOT / "custom_components/tater_satellite/manager.py").read_text())
        cls = next(node for node in source.body if isinstance(node, ast.ClassDef) and any(isinstance(item, ast.FunctionDef) and item.name == "_adopt_reported_device_text_style" for item in node.body))
        method = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == "_adopt_reported_device_text_style")
        scope = {"SatelliteRuntime": SimpleNamespace, "Any": object, "supports_screen_text_style": settings.supports_screen_text_style}
        exec(compile(ast.Module(body=[method], type_ignores=[]), "<actual manager method>", "exec"), scope)
        adopt = scope[method.name]
        manager = SimpleNamespace(data={}, store=mock.Mock())
        runtime = SimpleNamespace(board="athena", capabilities=CAPS, settings_sync_state="confirmed", record={"overrides": {"screen_brightness": 43}})
        payload = {"ok": True, "settings": {"screen_text_style": "matrix"}}
        self.assertTrue(adopt(manager, runtime, payload))
        self.assertEqual(runtime.record["overrides"], {"screen_brightness": 43, "screen_text_style": "matrix"})
        self.assertFalse(adopt(manager, runtime, payload))
        for value in ("bad", None, {}, []):
            self.assertFalse(adopt(manager, runtime, {"settings": {"screen_text_style": value}}))
        self.assertFalse(adopt(manager, runtime, {"ok": False, "settings": {"screen_text_style": "smooth"}}))
        runtime.settings_sync_state = "sent"
        self.assertFalse(adopt(manager, runtime, {"settings": {"screen_text_style": "smooth"}}))
        manager.store.async_delay_save.assert_called_once()


if __name__ == "__main__":
    unittest.main()
