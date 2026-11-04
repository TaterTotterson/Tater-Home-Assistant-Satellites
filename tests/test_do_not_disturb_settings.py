from __future__ import annotations

import ast
import asyncio
import importlib.util
from pathlib import Path
import time
import types
import unittest


ROOT = Path(__file__).resolve().parents[1]
SETTINGS_PATH = ROOT / "custom_components" / "tater_satellite" / "settings.py"
MANAGER_PATH = ROOT / "custom_components" / "tater_satellite" / "manager.py"
SPEC = importlib.util.spec_from_file_location(
    "tater_satellite_do_not_disturb", SETTINGS_PATH
)
assert SPEC is not None and SPEC.loader is not None
settings = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(settings)


def load_async_push_settings():
    """Load the settings push method without importing Home Assistant."""
    tree = ast.parse(MANAGER_PATH.read_text(encoding="utf-8"))
    manager = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "TaterSatelliteManager"
    )
    method = next(
        node
        for node in manager.body
        if isinstance(node, ast.AsyncFunctionDef)
        and node.name == "async_push_settings"
    )
    module = ast.Module(
        body=[
            ast.ImportFrom(
                module="__future__",
                names=[ast.alias(name="annotations")],
                level=0,
            ),
            method,
        ],
        type_ignores=[],
    )
    namespace = {
        "time": time,
        "_settings_messages": lambda *_args, **_kwargs: [{"type": "settings"}],
    }
    exec(compile(ast.fix_missing_locations(module), MANAGER_PATH, "exec"), namespace)
    return namespace["async_push_settings"]


class DoNotDisturbSettingsTests(unittest.TestCase):
    CAPABLE = {"do_not_disturb": True, "do_not_disturb_version": 1}

    def test_defaults_match_tater(self) -> None:
        values = settings.normalize_settings({})
        self.assertIs(values["dnd_enabled"], False)
        self.assertIs(values["dnd_schedule_enabled"], False)
        self.assertEqual(values["dnd_start"], "22:00")
        self.assertEqual(values["dnd_end"], "07:00")

    def test_values_are_normalized(self) -> None:
        values = settings.normalize_settings(
            {
                "dnd_enabled": "on",
                "dnd_schedule_enabled": "true",
                "dnd_start": "9:05",
                "dnd_end": "25:00",
            }
        )
        self.assertIs(values["dnd_enabled"], True)
        self.assertIs(values["dnd_schedule_enabled"], True)
        self.assertEqual(values["dnd_start"], "09:05")
        self.assertEqual(values["dnd_end"], "07:00")

    def test_capable_echo_receives_dnd_and_utc_offset(self) -> None:
        values = settings.normalize_settings(
            {"dnd_schedule_enabled": True, "dnd_start": "23:30"}
        )
        for board in ("radar", "crown", "biscuit", "checkers"):
            payload = settings.firmware_payload(
                values,
                board=board,
                capabilities=self.CAPABLE,
                utc_offset_seconds=-8 * 60 * 60,
            )
            self.assertIs(payload["dnd_schedule_enabled"], True, board)
            self.assertEqual(payload["dnd_start"], "23:30", board)
            self.assertEqual(payload["dnd_end"], "07:00", board)
            self.assertEqual(payload["utc_offset_seconds"], -28800, board)

    def test_utc_offset_is_clamped_to_firmware_range(self) -> None:
        payload = settings.firmware_payload(
            settings.normalize_settings({}),
            board="radar",
            capabilities=self.CAPABLE,
            utc_offset_seconds=99 * 60 * 60,
        )
        self.assertEqual(payload["utc_offset_seconds"], 18 * 60 * 60)

    def test_firmware_without_capability_never_receives_dnd(self) -> None:
        values = settings.normalize_settings({"dnd_enabled": True})
        for board, capabilities in (
            ("radar", {}),
            ("radar", {"do_not_disturb": False}),
            ("voice_pe", {}),
        ):
            payload = settings.firmware_payload(
                values,
                board=board,
                capabilities=capabilities,
                utc_offset_seconds=0,
            )
            for key in settings.DND_SETTING_KEYS | {"utc_offset_seconds"}:
                self.assertNotIn(key, payload, (board, key))

    def test_panel_section_is_device_scoped_and_capability_gated(self) -> None:
        section = next(
            row for row in settings.SETTINGS_SCHEMA if row["section"] == "dnd"
        )
        self.assertEqual(section["scopes"], ["device"])
        self.assertEqual(section["required_capability"], "do_not_disturb")
        fields = {field["key"]: field for field in section["fields"]}
        self.assertEqual(set(fields), settings.DND_SETTING_KEYS)
        for key in ("dnd_start", "dnd_end"):
            self.assertEqual(fields[key]["type"], "time")
            self.assertEqual(
                fields[key]["show_when"],
                {"key": "dnd_schedule_enabled", "equals": True},
            )

    def test_failed_offset_push_is_retried_before_offset_is_recorded(self) -> None:
        push_settings = load_async_push_settings()
        manager = types.SimpleNamespace(
            firmware_settings=lambda _device_id: {"utc_offset_seconds": -21600}
        )
        runtime = types.SimpleNamespace(
            connected=True,
            settings_push_baseline=0,
            settings_last_push=0.0,
            settings_push_count=0,
            settings_sync_state="",
            settings_sync_message="",
            settings_utc_offset=-18000,
            board="radar",
            capabilities=self.CAPABLE,
            device_id="test-satellite",
            settings_generation=lambda: 0,
            notify=lambda: None,
        )
        results = iter((False, True))

        async def async_send_json(_message):
            return next(results)

        runtime.async_send_json = async_send_json

        self.assertIs(asyncio.run(push_settings(manager, runtime)), False)
        self.assertEqual(runtime.settings_utc_offset, -18000)
        self.assertIs(asyncio.run(push_settings(manager, runtime)), True)
        self.assertEqual(runtime.settings_utc_offset, -21600)


if __name__ == "__main__":
    unittest.main()
