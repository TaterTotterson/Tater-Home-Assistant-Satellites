from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest
from urllib.parse import parse_qs, urlparse
import wave
from io import BytesIO


ROOT = Path(__file__).resolve().parents[1]
INTERCOM_PATH = ROOT / "custom_components" / "tater_satellite" / "intercom.py"
MANAGER_PATH = ROOT / "custom_components" / "tater_satellite" / "manager.py"
HTTP_PATH = ROOT / "custom_components" / "tater_satellite" / "http.py"
PANEL_PATH = (
    ROOT
    / "custom_components"
    / "tater_satellite"
    / "frontend"
    / "tater-satellite-panel.js"
)

SPEC = importlib.util.spec_from_file_location("tater_intercom_test", INTERCOM_PATH)
assert SPEC is not None and SPEC.loader is not None
intercom = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(intercom)


class FakeBus:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    def async_fire(self, event_type: str, payload: dict) -> None:
        self.events.append((event_type, dict(payload)))


class FakeHass:
    def __init__(self) -> None:
        self.bus = FakeBus()


class FakeManager:
    def __init__(self) -> None:
        self.hass = FakeHass()
        self.runtimes: dict[str, FakeRuntime] = {}

    def public_base_url(self) -> str:
        return "http://homeassistant.local:8123"


class FakeRuntime:
    def __init__(
        self,
        manager: FakeManager,
        device_id: str,
        *,
        active_media: bool = False,
    ) -> None:
        self.manager = manager
        self.device_id = device_id
        self.name = device_id.replace("-", " ").title()
        self.room = self.name
        self.connected = True
        self.server_base_url = "http://ha.test:8123"
        self.media_session = {
            "active": active_media,
            "group_id": "music-group" if active_media else "",
        }
        self.capabilities = {"tts_overlays": active_media}
        self.intercom_session: dict = {}
        self.sent: list[tuple[str, dict]] = []
        self.logs: list[tuple[str, str, str]] = []
        self.notifications = 0
        manager.runtimes[device_id] = self

    async def async_send(self, kind: str, payload: dict) -> bool:
        self.sent.append((kind, dict(payload)))
        return True

    def add_log(self, level: str, message: str, *, kind: str = "log") -> None:
        self.logs.append((level, message, kind))

    def notify(self) -> None:
        self.notifications += 1


class IntercomHelpersTests(unittest.TestCase):
    def test_held_button_voice_turn_is_identified(self) -> None:
        self.assertTrue(
            intercom.is_intercom_request(
                {
                    "wake_word": "push to intercom",
                    "source": "center_button_hold",
                }
            )
        )
        self.assertTrue(intercom.is_intercom_request({"source": "intercom-hold"}))
        self.assertFalse(
            intercom.is_intercom_request(
                {"wake_word": "hey tater", "source": "local_wake"}
            )
        )

    def test_pcm_is_wrapped_as_wav_without_changing_format(self) -> None:
        wav_bytes = intercom.pcm_to_wav(
            b"\x00\x01" * 160,
            {"rate": 16_000, "width": 2, "channels": 1},
        )

        with wave.open(BytesIO(wav_bytes), "rb") as wav_file:
            self.assertEqual(wav_file.getframerate(), 16_000)
            self.assertEqual(wav_file.getsampwidth(), 2)
            self.assertEqual(wav_file.getnchannels(), 1)
            self.assertEqual(wav_file.getnframes(), 160)


class IntercomRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_capture_broadcasts_to_peers_and_overlays_active_music(self) -> None:
        manager = FakeManager()
        source = FakeRuntime(manager, "kitchen")
        idle_target = FakeRuntime(manager, "office")
        music_target = FakeRuntime(manager, "bedroom", active_media=True)
        coordinator = intercom.TaterIntercomCoordinator(manager)

        ok, error = coordinator.start_capture(
            source,
            {
                "wake_word": "push to intercom",
                "source": "center_button_hold",
                "audio_format": {"rate": 16_000, "width": 2, "channels": 1},
            },
        )
        self.assertTrue(ok)
        self.assertEqual(error, "")
        self.assertTrue(source.intercom_session["active"])
        self.assertTrue(coordinator.add_audio(source, b"\x00\x01" * 8_000))

        capture = coordinator.finish_capture(source, abort=False)
        self.assertIsNotNone(capture)
        result = await coordinator.async_broadcast(source, capture)

        self.assertEqual(result["phase"], "broadcast")
        self.assertEqual(result["sent_count"], 2)
        self.assertEqual(source.sent, [])
        self.assertEqual(idle_target.sent[0][0], "play.url")
        self.assertEqual(music_target.sent[0][0], "audio.overlay.start")
        self.assertEqual(
            music_target.sent[0][1]["foreground"]["kind"],
            "intercom",
        )
        playback_url = idle_target.sent[0][1]["url"]
        parsed = urlparse(playback_url)
        clip_id = Path(parsed.path).stem
        token = parse_qs(parsed.query)["token"][0]
        body = coordinator.clip_bytes(clip_id, token)
        self.assertIsNotNone(body)
        self.assertTrue(body.startswith(b"RIFF"))
        self.assertIsNone(coordinator.clip_bytes(clip_id, "wrong-token"))
        phases = [payload["phase"] for _event, payload in manager.hass.bus.events]
        self.assertEqual(phases, ["started", "broadcast"])

    async def test_aborted_capture_is_not_sent(self) -> None:
        manager = FakeManager()
        source = FakeRuntime(manager, "kitchen")
        target = FakeRuntime(manager, "office")
        coordinator = intercom.TaterIntercomCoordinator(manager)
        coordinator.start_capture(
            source,
            {"source": "center_button_hold"},
        )
        coordinator.add_audio(source, b"\x00\x01" * 8_000)

        capture = coordinator.finish_capture(source, abort=True)

        self.assertIsNotNone(capture)
        self.assertTrue(capture["aborted"])
        self.assertEqual(target.sent, [])
        self.assertEqual(coordinator.history[0]["phase"], "cancelled")


class IntercomIntegrationTests(unittest.TestCase):
    def test_websocket_intercepts_intercom_before_assist(self) -> None:
        source = MANAGER_PATH.read_text(encoding="utf-8")

        self.assertIn("if is_intercom_request(payload):", source)
        self.assertIn("if self.intercom.add_audio(runtime, data):", source)
        self.assertIn("self.intercom.async_broadcast(runtime, capture)", source)
        self.assertIn('"intercom": True', source)

    def test_temporary_clip_route_and_panel_status_are_exposed(self) -> None:
        http_source = HTTP_PATH.read_text(encoding="utf-8")
        panel_source = PANEL_PATH.read_text(encoding="utf-8")

        self.assertIn("class IntercomClipView", http_source)
        self.assertIn("intercom.clip_bytes", http_source)
        self.assertIn("Push-to-talk intercom", panel_source)
        self.assertIn("Temporary memory only", panel_source)


if __name__ == "__main__":
    unittest.main()
