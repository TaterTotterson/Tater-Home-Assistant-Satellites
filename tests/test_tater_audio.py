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
SPEC = importlib.util.spec_from_file_location("tater_satellite_media", MEDIA_PATH)
assert SPEC is not None and SPEC.loader is not None
media = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(media)


class TaterAudioTests(unittest.TestCase):
    def test_pair_values_are_bounded_for_the_firmware_protocol(self) -> None:
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

    def test_bridge_exposes_media_players_and_sync_commands(self) -> None:
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

        self.assertIn("Platform.MEDIA_PLAYER", const)
        self.assertIn("self.pending_requests", manager)
        self.assertIn('"audio.clock.sync"', coordinator)
        self.assertIn('"media.session.prepare"', coordinator)
        self.assertIn('"media.session.commit"', coordinator)
        self.assertIn('"media.session.adjust"', coordinator)
        self.assertIn("MediaPlayerEntityFeature.GROUPING", player)

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
        http = (ROOT / "custom_components" / "tater_satellite" / "http.py").read_text()

        self.assertIn('this.tabButton("audio", "Tater Audio")', panel)
        self.assertIn('this.api("POST", "stereo-pairs"', panel)
        self.assertIn('class StereoPairView(', http)
        self.assertIn('class StereoPairDeleteView(', http)


class _FakeEntry:
    @staticmethod
    def async_create_background_task(_hass, coroutine, _name):
        import asyncio

        return asyncio.create_task(coroutine)


class _FakeRuntime:
    def __init__(self, device_id: str) -> None:
        self.device_id = device_id
        self.name = device_id.title()
        self.connected = True
        self.server_base_url = "http://ha.local:8123"
        self.media_session = {}
        self.capabilities = {
            "synchronized_media_sessions": True,
            "media_playhead_telemetry": True,
            "media_drift_correction": True,
            "media_rate_slew": True,
            "media_render_clock": True,
            "audio_session_version": 4,
            "media_sample_rate_hz": 48000,
            "media_output_latency_frames": 480,
        }
        self.requests = []
        self.sent = []

    def effective_settings(self):
        return {"volume_percent": 80, "muted": False}

    async def async_request(self, kind, payload, *, timeout):
        self.requests.append((kind, payload, timeout))
        if kind == "audio.clock.sync":
            sent = int(payload["server_send_us"])
            return {
                "ok": True,
                "satellite_receive_us": sent + 1000,
                "satellite_send_us": sent + 1100,
            }
        if kind == "media.session.prepare":
            return {
                "ok": True,
                "sample_rate_hz": 48000,
                "output_latency_frames": 480,
            }
        return {"ok": True}

    async def async_send(self, kind, payload):
        self.sent.append((kind, payload))
        return True


class TaterAudioRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_single_satellite_still_receives_original_media_url(self) -> None:
        runtime = _FakeRuntime("solo")
        manager = SimpleNamespace(
            runtimes={"solo": runtime}, entry=_FakeEntry(), hass=None
        )
        coordinator = media.TaterMediaCoordinator(manager)
        manager.media = coordinator
        try:
            with mock.patch.object(coordinator, "_create_shared_relay") as create_relay:
                await coordinator.async_play("solo", "http://ha.local/solo.mp3")
            create_relay.assert_not_called()
            prepares = [
                payload for kind, payload, _timeout in runtime.requests
                if kind == "media.session.prepare"
            ]
            self.assertEqual(prepares[0]["media"]["url"], "http://ha.local/solo.mp3")
        finally:
            await coordinator.async_shutdown()

    async def test_saved_pair_uses_prepare_commit_and_left_right_routes(self) -> None:
        manager = SimpleNamespace(
            data={
                "stereo_pairs": {
                    "office": {
                        "id": "office",
                        "name": "Office",
                        "left_device_id": "left",
                        "right_device_id": "right",
                    }
                }
            },
            runtimes={
                "left": _FakeRuntime("left"),
                "right": _FakeRuntime("right"),
            },
            entry=_FakeEntry(),
            hass=None,
        )

        async def save():
            return None

        manager.async_save = save
        manager.public_base_url = lambda: "http://ha.local:8123"
        coordinator = media.TaterMediaCoordinator(manager)
        manager.media = coordinator
        coordinator.setup()
        relay = SimpleNamespace(
            id="shared-relay",
            url_for=lambda base: f"{base}/api/tater/satellite/v1/media/shared/shared-relay/song.flac?token=one",
        )
        try:
            with mock.patch.object(
                coordinator, "_create_shared_relay", new=mock.AsyncMock(return_value=relay)
            ) as create_relay:
                session = await coordinator.async_play(
                    "stereo:office", "http://ha.local/song.flac", title="Song"
                )
            create_relay.assert_awaited_once_with(
                "http://ha.local/song.flac", None, ""
            )
            self.assertEqual(session["state"], "buffering")
            self.assertEqual(session["shared_relay_id"], "shared-relay")
            self.assertEqual(
                [route["channel"] for route in session["routes"]],
                ["left", "right"],
            )
            prepared_urls = []
            for runtime in manager.runtimes.values():
                kinds = [kind for kind, _payload, _timeout in runtime.requests]
                self.assertEqual(kinds.count("audio.clock.sync"), 5)
                self.assertIn("media.session.prepare", kinds)
                self.assertIn("media.session.commit", kinds)
                prepared_urls.extend(
                    payload["media"]["url"]
                    for kind, payload, _timeout in runtime.requests
                    if kind == "media.session.prepare"
                )
            self.assertEqual(len(prepared_urls), 2)
            self.assertEqual(prepared_urls[0], prepared_urls[1])
            self.assertIn("/media/shared/shared-relay/", prepared_urls[0])

            for runtime in manager.runtimes.values():
                coordinator.handle_message(
                    runtime,
                    "media.session.started",
                    {"group_id": session["group_id"], "session_id": session["session_id"]},
                )
            self.assertEqual(session["state"], "playing")

            with mock.patch.object(
                coordinator, "_create_shared_relay", new=mock.AsyncMock(return_value=relay)
            ) as reuse_relay:
                await coordinator.async_seek("stereo:office", 5.0)
            reuse_relay.assert_awaited_once_with(
                "http://ha.local/song.flac", None, "shared-relay"
            )
            session = coordinator.session_for_target("stereo:office")
            self.assertEqual(session["start_position_ms"], 5000)
            for runtime in manager.runtimes.values():
                prepares = [
                    payload for kind, payload, _timeout in runtime.requests
                    if kind == "media.session.prepare"
                ]
                self.assertEqual(len(prepares), 2)
                self.assertEqual(prepares[1]["media"]["start_position_ms"], 5000)

            for runtime in manager.runtimes.values():
                coordinator.handle_message(
                    runtime,
                    "media.session.finished",
                    {
                        "group_id": session["group_id"],
                        "session_id": session["session_id"],
                        "ok": True,
                    },
                )
            self.assertNotIn(session["group_id"], coordinator.sessions)
        finally:
            await coordinator.async_shutdown()

    async def test_rebuffered_stereo_member_jumps_once_only_after_recovery(self) -> None:
        now = media._monotonic_us()
        left = _FakeRuntime("left")
        right = _FakeRuntime("right")
        manager = SimpleNamespace(
            runtimes={"left": left, "right": right},
            entry=_FakeEntry(),
            hass=None,
        )
        coordinator = media.TaterMediaCoordinator(manager)
        manager.media = coordinator
        coordinator.sessions["group"] = {
            "group_id": "group",
            "session_id": "session",
            "members": ["left", "right"],
            "routes": [
                {"device_id": "left", "channel": "left", "delay_ms": 0},
                {"device_id": "right", "channel": "right", "delay_ms": 0},
            ],
            "clock_offsets_us": {"left": 0, "right": 0},
            "clock_sync_us": now,
            "audible_start_server_us": now - 1_000_000,
            "start_position_frames": {"left": 0, "right": 0},
            "phase_ema": {},
            "phase_direction": {},
            "phase_stable": {},
            "pending_rejoin": {},
            "playheads": {
                "left": {
                    "session_id": "session",
                    "sample_rate_hz": 48000,
                    "satellite_time_us": now,
                    "rendered_frames": 48000,
                    "rebuffering": False,
                }
            },
            "finished": set(),
        }
        stalled = {
            "group_id": "group",
            "session_id": "session",
            "sample_rate_hz": 48000,
            "satellite_time_us": now,
            "rendered_frames": 0,
            "rebuffering": True,
            "rejoin_count": 0,
        }
        coordinator.handle_message(right, "media.session.playhead", stalled)
        with mock.patch.object(media, "ADJUST_INTERVAL_SECONDS", 0.01):
            task = asyncio.create_task(coordinator._sync_loop("group"))
            coordinator.sync_tasks["group"] = task
            try:
                await asyncio.sleep(0.04)
                self.assertFalse(
                    [item for item in right.requests if item[0] == "media.session.adjust"]
                )
                coordinator.handle_message(
                    right,
                    "media.session.playhead",
                    {**stalled, "rebuffering": False, "rejoin_count": 1},
                )
                await asyncio.sleep(0.08)
                jumps = [
                    payload for kind, payload, _timeout in right.requests
                    if kind == "media.session.adjust" and payload["mode"] == "jump"
                ]
                self.assertEqual(len(jumps), 1)
                self.assertEqual(jumps[0]["correction_frames"], 24_000)
                self.assertNotIn(
                    "right", coordinator.sessions["group"]["pending_rejoin"]
                )
            finally:
                await coordinator.async_shutdown()


if __name__ == "__main__":
    unittest.main()
