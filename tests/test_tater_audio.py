from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest


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
        coordinator = media.TaterMediaCoordinator(manager)
        manager.media = coordinator
        coordinator.setup()
        try:
            session = await coordinator.async_play(
                "stereo:office", "http://ha.local/song.flac", title="Song"
            )
            self.assertEqual(session["state"], "buffering")
            self.assertEqual(
                [route["channel"] for route in session["routes"]],
                ["left", "right"],
            )
            for runtime in manager.runtimes.values():
                kinds = [kind for kind, _payload, _timeout in runtime.requests]
                self.assertEqual(kinds.count("audio.clock.sync"), 5)
                self.assertIn("media.session.prepare", kinds)
                self.assertIn("media.session.commit", kinds)

            group_id = session["group_id"]
            session_id = session["session_id"]
            for runtime in manager.runtimes.values():
                coordinator.handle_message(
                    runtime,
                    "media.session.started",
                    {"group_id": group_id, "session_id": session_id},
                )
            self.assertEqual(session["state"], "playing")

            for runtime in manager.runtimes.values():
                coordinator.handle_message(
                    runtime,
                    "media.session.finished",
                    {"group_id": group_id, "session_id": session_id, "ok": True},
                )
            self.assertNotIn(group_id, coordinator.sessions)
        finally:
            await coordinator.async_shutdown()


if __name__ == "__main__":
    unittest.main()
