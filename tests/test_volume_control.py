from __future__ import annotations

import ast
import importlib.util
import json
from pathlib import Path
from types import MethodType, SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock


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
        manager_path = (
            ROOT / "custom_components" / "tater_satellite" / "manager.py"
        )
        module = ast.parse(manager_path.read_text(encoding="utf-8"))
        groups = None
        for node in module.body:
            if not isinstance(node, ast.Assign):
                continue
            if any(
                isinstance(target, ast.Name)
                and target.id == "_SETTINGS_WIRE_GROUPS"
                for target in node.targets
            ):
                groups = ast.literal_eval(node.value)
                break

        self.assertIsNotNone(groups)
        audio_group = next(group for group in groups if "aec_enabled" in group)
        self.assertIn("volume_percent", audio_group)
        self.assertIn("output_channel_mode", audio_group)

    def test_manifest_version_is_bumped(self) -> None:
        manifest = json.loads(
            (
                ROOT
                / "custom_components"
                / "tater_satellite"
                / "manifest.json"
            ).read_text(encoding="utf-8")
        )

        self.assertEqual(manifest["version"], "1.4.18")


def volume_methods():
    path = ROOT / "custom_components/tater_satellite/manager.py"
    tree = ast.parse(path.read_text())
    manager = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "TaterSatelliteManager")
    names = {"effective_settings", "_adopt_reported_device_volume", "async_set_device_settings"}
    methods = [node for node in manager.body if getattr(node, "name", "") in names]
    global_keys = next(
        ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "_GLOBAL_WAKE_VERIFIER_KEYS" for target in node.targets)
    )
    scope = {
        "Any": object, "SatelliteRuntime": object,
        "text": lambda value: str(value or "").strip(),
        "normalize_settings": settings.normalize_settings,
        "SHARED_WAKE_MODEL_SETTING_KEYS": settings.SHARED_WAKE_MODEL_SETTING_KEYS,
        "_GLOBAL_WAKE_VERIFIER_KEYS": global_keys,
    }
    exec(compile(ast.Module(body=methods, type_ignores=[]), str(path), "exec"), scope)
    return {name: scope[name] for name in names}


class VolumeSynchronizationTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.methods = volume_methods()

    def setUp(self):
        self.manager = SimpleNamespace(
            data={"global_settings": {"volume_percent": 80}, "devices": {}},
            runtimes={}, _settings_cache=None, store=SimpleNamespace(async_delay_save=Mock()),
            async_save=AsyncMock(), async_push_settings=AsyncMock(return_value=True),
        )
        for name, method in self.methods.items():
            setattr(self.manager, name, MethodType(method, self.manager))
        self.manager._resolve_settings = lambda device_id: {
            **self.manager.data["global_settings"],
            **self.manager.runtimes[device_id].record["overrides"],
        }
        self.runtime = self.add_runtime("sat1")
        self.other = self.add_runtime("other")

    def add_runtime(self, device_id):
        record = {"overrides": {"aec_enabled": True}}
        runtime = SimpleNamespace(
            device_id=device_id, name=device_id, record=record,
            settings_sync_state="sent", connected=True, notify=Mock(),
            effective_settings=lambda: self.manager.effective_settings(device_id),
            public_snapshot=lambda: {"settings": self.manager.effective_settings(device_id)},
        )
        self.manager.runtimes[device_id] = runtime
        self.manager.data["devices"][device_id] = record
        return runtime

    def adopt(self, value, **extra):
        return self.manager._adopt_reported_device_volume(
            self.runtime, {"source": "device", "settings": {"volume_percent": value}, **extra},
        )

    def test_physical_change_is_saved_before_full_settings_confirmation(self):
        self.assertTrue(self.adopt(35))
        self.assertEqual(self.runtime.effective_settings()["volume_percent"], 35)
        self.assertEqual(self.runtime.record["overrides"], {"aec_enabled": True, "volume_percent": 35})
        self.assertEqual(self.runtime.settings_sync_state, "sent")
        self.assertEqual(self.other.effective_settings()["volume_percent"], 80)
        self.assertEqual(self.manager.data["global_settings"]["volume_percent"], 80)
        callback, delay = self.manager.store.async_delay_save.call_args.args
        self.assertEqual(callback()["devices"]["sat1"]["overrides"]["volume_percent"], 35)
        self.assertEqual(delay, 1.0)
        self.manager.async_push_settings.assert_not_called()

    def test_zero_volume_and_repeated_changes_are_preserved(self):
        for volume in (35, 0, 100, 5):
            self.assertTrue(self.adopt(volume))
            self.assertEqual(self.runtime.effective_settings()["volume_percent"], volume)
        self.manager.store.async_delay_save.reset_mock()
        self.assertFalse(self.adopt(5))
        self.manager.store.async_delay_save.assert_not_called()

    def test_unconfirmed_status_cannot_undo_a_physical_change(self):
        self.assertTrue(self.adopt(35))
        for state in ("sending", "sent", "failed", "never"):
            self.runtime.settings_sync_state = state
            self.assertFalse(self.manager._adopt_reported_device_volume(
                self.runtime, {"live_settings": {"volume_percent": 80}},
            ))
            self.assertEqual(self.runtime.effective_settings()["volume_percent"], 35)

    def test_confirmed_status_and_flat_device_deltas_remain_supported(self):
        self.runtime.settings_sync_state = "confirmed"
        self.assertTrue(self.manager._adopt_reported_device_volume(
            self.runtime, {"live_settings": {"volume_percent": 45}},
        ))
        self.runtime.settings_sync_state = "sent"
        self.assertTrue(self.manager._adopt_reported_device_volume(
            self.runtime, {"source": "device", "volume_percent": 30},
        ))
        self.assertEqual(self.runtime.effective_settings()["volume_percent"], 30)

    def test_failed_or_invalid_reports_do_not_change_the_saved_volume(self):
        for value in (None, True, "bad", -1, 101, 50.5, float("nan"), float("inf")):
            with self.subTest(value=value):
                self.assertFalse(self.adopt(value))
        for extra in ({"error": "rejected"}, {"ok": False}):
            self.assertFalse(self.adopt(25, **extra))
        self.assertFalse(self.manager._adopt_reported_device_volume(
            self.runtime, {"source": "device", "settings": {"muted": True}},
        ))
        self.assertEqual(self.runtime.effective_settings()["volume_percent"], 80)
        self.manager.store.async_delay_save.assert_not_called()

    def test_a_physical_change_invalidates_only_its_cached_settings(self):
        self.manager._settings_cache = {"sat1": {"volume_percent": 80}, "other": {"volume_percent": 60}}
        self.assertTrue(self.adopt(25))
        self.assertEqual(self.runtime.effective_settings()["volume_percent"], 25)
        self.assertEqual(self.manager._settings_cache["other"]["volume_percent"], 60)

    async def test_later_unrelated_settings_push_keeps_the_physical_volume(self):
        self.assertTrue(self.adopt(25))
        sent = []

        async def push(runtime):
            sent.append(settings.firmware_payload(runtime.effective_settings(), board="satellite1"))
            return True

        self.manager.async_push_settings.side_effect = push
        await self.manager.async_set_device_settings("sat1", {"aec_enabled": False})
        self.assertEqual(sent[0]["volume_percent"], 25)
        self.assertFalse(sent[0]["aec_enabled"])
        self.assertEqual(self.runtime.effective_settings()["volume_percent"], 25)


if __name__ == "__main__":
    unittest.main()
