from __future__ import annotations

import asyncio
import ast
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
MEDIA_PATH = ROOT / "custom_components" / "tater_satellite" / "media.py"
SENDSPIN_PATH = ROOT / "custom_components" / "tater_satellite" / "sendspin.py"
SPEC = importlib.util.spec_from_file_location("tater_satellite_media", MEDIA_PATH)
assert SPEC is not None and SPEC.loader is not None
media = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(media)


class TaterAudioTests(unittest.TestCase):
    def test_pair_values_are_bounded_for_sendspin_routing(self) -> None:
        row = media.TaterMediaCoordinator._normalize_pair(
            {
                "name": "Office",
                "left_device_id": "left",
                "right_device_id": "right",
                "left_delay_ms": -10,
                "right_delay_ms": 900,
                "left_volume_percent": 125,
                "right_volume_percent": -1,
            },
            "office",
        )

        self.assertEqual(row["target"], "stereo:office")
        self.assertEqual(row["left_delay_ms"], 0)
        self.assertEqual(row["right_delay_ms"], 250)
        self.assertEqual(row["left_volume_percent"], 100)
        self.assertEqual(row["right_volume_percent"], 0)

    def test_bridge_uses_sendspin_and_removes_legacy_sync_protocol(self) -> None:
        const = (
            ROOT / "custom_components" / "tater_satellite" / "const.py"
        ).read_text()
        manager = (
            ROOT / "custom_components" / "tater_satellite" / "manager.py"
        ).read_text()
        player = (
            ROOT / "custom_components" / "tater_satellite" / "media_player.py"
        ).read_text()
        coordinator = MEDIA_PATH.read_text()
        sendspin = SENDSPIN_PATH.read_text()

        self.assertIn("Platform.MEDIA_PLAYER", const)
        self.assertIn('"sendspin_source": True', manager)
        self.assertIn('"output_channel_mode"', manager)
        self.assertIn("class SendspinStream", sendspin)
        self.assertIn('"stream/start"', sendspin)
        self.assertIn('"stream/end"', sendspin)
        self.assertIn("MediaPlayerEntityFeature.GROUPING", player)
        retired = (
            "audio.clock.sync",
            "media.session.prepare",
            "media.session.commit",
            "media.session.adjust",
            "media.session.stop",
        )
        for command in retired:
            self.assertNotIn(command, coordinator)
            self.assertNotIn(command, manager)

    def test_manifest_loads_home_assistant_ffmpeg(self) -> None:
        import json

        manifest = json.loads(
            (
                ROOT
                / "custom_components"
                / "tater_satellite"
                / "manifest.json"
            ).read_text()
        )
        self.assertIn("ffmpeg", manifest["dependencies"])

    def test_device_class_uses_stable_home_assistant_import(self) -> None:
        player_path = (
            ROOT / "custom_components" / "tater_satellite" / "media_player.py"
        )
        tree = ast.parse(player_path.read_text(encoding="utf-8"))
        imported_names: dict[str, set[str]] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported_names.setdefault(node.module, set()).update(
                    alias.name for alias in node.names
                )

        self.assertIn(
            "MediaPlayerDeviceClass",
            imported_names["homeassistant.components.media_player"],
        )
        self.assertNotIn(
            "MediaPlayerDeviceClass",
            imported_names["homeassistant.components.media_player.const"],
        )

    def test_panel_can_create_and_remove_stereo_pairs(self) -> None:
        panel = (
            ROOT
            / "custom_components"
            / "tater_satellite"
            / "frontend"
            / "tater-satellite-panel.js"
        ).read_text()
        http = (
            ROOT / "custom_components" / "tater_satellite" / "http.py"
        ).read_text()

        self.assertIn('this.tabButton("audio", "Tater Audio")', panel)
        self.assertIn('this.api("POST", "stereo-pairs"', panel)
        self.assertIn("class StereoPairView(", http)
        self.assertIn("class StereoPairDeleteView(", http)
        self.assertNotIn("SharedMediaView", http)


class _FakeEntry:
    @staticmethod
    def async_create_background_task(_hass, coroutine, _name):
        return asyncio.create_task(coroutine)


class _FakeRuntime:
    def __init__(self, device_id: str) -> None:
        self.device_id = device_id
        self.name = device_id.title()
        self.connected = True
        self.remote = f"192.0.2.{1 if device_id == 'left' else 2}"
        self.media_session = {}
        self.last_error = ""
        self.capabilities = {
            "sendspin_player": True,
            "sendspin_version": 1,
            "sendspin_output_channel_selection": True,
        }

    def effective_settings(self):
        return {"volume_percent": 80, "muted": False}


class _FakeStream:
    def __init__(self) -> None:
        self.task = None
        self.running = asyncio.Event()
        self.release = asyncio.Event()
        self.stopped = False

    def bind_task(self, task) -> None:
        self.task = task

    async def run(self) -> None:
        self.running.set()
        await self.release.wait()

    async def wait_started(self) -> None:
        await self.running.wait()

    async def stop(self) -> None:
        self.stopped = True
        if self.task is not None and not self.task.done():
            self.task.cancel()
            with self.assert_cancelled():
                await self.task

    @staticmethod
    def assert_cancelled():
        import contextlib

        return contextlib.suppress(asyncio.CancelledError)

    def position_seconds(self) -> float:
        return 12.5


class TaterAudioRuntimeTests(unittest.IsolatedAsyncioTestCase):
    def _manager(self, *, pair: bool = False):
        data = {"stereo_pairs": {}}
        runtimes = {"left": _FakeRuntime("left"), "right": _FakeRuntime("right")}
        if pair:
            data["stereo_pairs"]["office"] = {
                "id": "office",
                "name": "Office",
                "left_device_id": "left",
                "right_device_id": "right",
                "left_delay_ms": 15,
                "right_delay_ms": 25,
                "left_volume_percent": 90,
                "right_volume_percent": 80,
            }
        manager = SimpleNamespace(
            data=data,
            runtimes=runtimes,
            entry=_FakeEntry(),
            hass=None,
        )

        async def save():
            return None

        manager.setting_updates = []

        async def set_device_settings(device_id, values):
            manager.setting_updates.append((device_id, dict(values)))

        manager.async_save = save
        manager.async_set_device_settings = set_device_settings
        coordinator = media.TaterMediaCoordinator(manager)
        manager.media = coordinator
        coordinator.setup()
        return manager, coordinator

    async def test_single_satellite_uses_one_sendspin_stream(self) -> None:
        manager, coordinator = self._manager()
        stream = _FakeStream()
        try:
            with mock.patch.object(coordinator, "_new_stream", return_value=stream):
                session = await coordinator.async_play(
                    "left", "http://ha.local/solo.mp3"
                )
            self.assertEqual(session["state"], "playing")
            self.assertEqual(session["routes"][0]["channel"], "stereo")
            self.assertEqual(
                manager.runtimes["left"].media_session["transport"], "sendspin"
            )
            self.assertEqual(coordinator.media_position("left"), 12.5)
        finally:
            await coordinator.async_shutdown()
        self.assertTrue(stream.stopped)

    async def test_saved_pair_routes_left_and_right_through_one_stream(self) -> None:
        manager, coordinator = self._manager(pair=True)
        first = _FakeStream()
        second = _FakeStream()
        try:
            with mock.patch.object(
                coordinator, "_new_stream", side_effect=[first, second]
            ):
                session = await coordinator.async_play(
                    "stereo:office", "http://ha.local/song.flac", title="Song"
                )
                self.assertEqual(
                    [route["channel"] for route in session["routes"]],
                    ["left", "right"],
                )
                self.assertEqual(
                    [route["trim_percent"] for route in session["routes"]],
                    [90, 80],
                )
                self.assertEqual(coordinator.output_channel_mode("left"), "left")
                self.assertEqual(coordinator.output_channel_mode("right"), "right")

                await coordinator.async_seek("stereo:office", 5.0)
                replacement = coordinator.session_for_target("stereo:office")
                self.assertEqual(replacement["start_position_seconds"], 5.0)
                self.assertTrue(first.stopped)
        finally:
            await coordinator.async_shutdown()

    async def test_multiroom_standalone_routes_are_mono(self) -> None:
        manager, coordinator = self._manager()
        coordinator.entities = {
            "left": SimpleNamespace(entity_id="media_player.left"),
            "right": SimpleNamespace(entity_id="media_player.right"),
        }
        await coordinator.async_join("left", ["media_player.right"])
        targets, routes = coordinator._play_routes("left")
        self.assertEqual(targets, ["left", "right"])
        self.assertEqual([route["channel"] for route in routes], ["mono", "mono"])

        stream = _FakeStream()
        try:
            with mock.patch.object(coordinator, "_new_stream", return_value=stream):
                await coordinator.async_play(
                    "left", "http://ha.local/group.flac"
                )
            await coordinator.async_set_volume("left", 55)
            self.assertEqual(
                manager.setting_updates,
                [
                    ("left", {"volume_percent": 55}),
                    ("right", {"volume_percent": 55}),
                ],
            )
        finally:
            await coordinator.async_shutdown()


if __name__ == "__main__":
    unittest.main()
