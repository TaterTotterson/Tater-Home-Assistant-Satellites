"""Identify routing and announcement playback without a running HA instance."""

from __future__ import annotations

import ast
import asyncio
import contextlib
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock


ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components/tater_satellite"


class HomeAssistantError(Exception):
    """Stand-in for HA's service/TTS errors."""


class ClientError(Exception):
    """Stand-in for aiohttp's provider/network errors."""


def load_method(filename, class_name, method_name, **scope):
    """Execute the production method without importing the HA integration."""
    path = COMPONENT / filename
    module = ast.parse(path.read_text(encoding="utf-8"))
    cls = next(
        node for node in module.body
        if isinstance(node, ast.ClassDef) and node.name == class_name
    )
    method = next(
        node for node in cls.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == method_name
    )
    future = ast.ImportFrom(
        module="__future__", names=[ast.alias(name="annotations")], level=0
    )
    extracted = ast.fix_missing_locations(
        ast.Module(body=[future, method], type_ignores=[])
    )
    exec(compile(extracted, str(path), "exec"), scope)
    return scope[method_name]


MANAGER_SOURCE = ast.parse((COMPONENT / "manager.py").read_text(encoding="utf-8"))
IDENTIFY_TEXT = next(
    ast.literal_eval(node.value)
    for node in MANAGER_SOURCE.body
    if isinstance(node, ast.Assign)
    and any(
        isinstance(target, ast.Name) and target.id == "_IDENTIFY_SATELLITE_TEXT"
        for target in node.targets
    )
)
identify = load_method(
    "manager.py", "TaterSatelliteManager", "async_identify",
    _IDENTIFY_SATELLITE_TEXT=IDENTIFY_TEXT,
    HomeAssistantError=HomeAssistantError,
    ClientError=ClientError,
)


class IdentifyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.announce = AsyncMock()
        self.runtime = SimpleNamespace(
            connected=True,
            name="Kitchen Echo",
            server_base_url="http://ha.lan:8123",
            assist_entity=SimpleNamespace(async_internal_announce=self.announce),
            async_send=AsyncMock(),
        )
        self.tater = SimpleNamespace(
            settings=Mock(return_value={"assistant_mode": "home_assistant"}),
            async_synthesize=AsyncMock(return_value=("audio/wav", b"voice audio")),
            store_clip=Mock(return_value="test-clip"),
        )
        self.manager = SimpleNamespace(
            runtimes={"kitchen": self.runtime},
            tater_assistant=self.tater,
            public_base_url=Mock(return_value="http://homeassistant.local:8123"),
        )

    async def test_home_assistant_uses_selected_pipeline_announcement_without_chime(self):
        await identify(self.manager, "kitchen")
        self.announce.assert_awaited_once_with(
            message=IDENTIFY_TEXT, media_id=None, preannounce=False
        )
        self.assertIn("satellite", IDENTIFY_TEXT)
        self.tater.async_synthesize.assert_not_awaited()
        self.tater.store_clip.assert_not_called()
        self.runtime.async_send.assert_not_awaited()

    async def test_mini_tater_uses_configured_tts_and_serves_a_real_clip_url(self):
        self.tater.settings.return_value = {"assistant_mode": "tater"}
        await identify(self.manager, "kitchen")
        self.tater.async_synthesize.assert_awaited_once_with(IDENTIFY_TEXT)
        self.tater.store_clip.assert_called_once_with("audio/wav", b"voice audio")
        self.announce.assert_awaited_once_with(
            message=IDENTIFY_TEXT,
            media_id="http://ha.lan:8123/api/tater/satellite/v1/tater/audio/test-clip",
            preannounce=False,
        )
        self.manager.public_base_url.assert_not_called()
        self.runtime.async_send.assert_not_awaited()

    async def test_mini_tater_falls_back_to_public_base_url(self):
        self.tater.settings.return_value = {"assistant_mode": "tater"}
        self.runtime.server_base_url = ""
        await identify(self.manager, "kitchen")
        self.assertEqual(
            self.announce.call_args.kwargs["media_id"],
            "http://homeassistant.local:8123/api/tater/satellite/v1/tater/audio/test-clip",
        )

    async def test_missing_and_offline_satellites_do_not_generate_or_play_audio(self):
        for device_id in ("missing", "kitchen"):
            self.runtime.connected = False
            with self.subTest(device_id=device_id):
                with self.assertRaisesRegex(RuntimeError, "offline"):
                    await identify(self.manager, device_id)
        self.tater.settings.assert_not_called()
        self.tater.async_synthesize.assert_not_awaited()
        self.announce.assert_not_awaited()

    async def test_unready_assist_entity_does_not_silently_succeed(self):
        self.runtime.assist_entity = None
        with self.assertRaisesRegex(RuntimeError, "not ready"):
            await identify(self.manager, "kitchen")
        self.tater.async_synthesize.assert_not_awaited()

    async def test_empty_mini_tater_audio_is_not_published(self):
        self.tater.settings.return_value = {"assistant_mode": "tater"}
        self.tater.async_synthesize.return_value = ("audio/wav", b"")
        with self.assertRaisesRegex(RuntimeError, "TTS returned no audio"):
            await identify(self.manager, "kitchen")
        self.tater.store_clip.assert_not_called()
        self.announce.assert_not_awaited()

    async def test_synthesis_errors_are_reported_without_attempting_playback(self):
        self.tater.settings.return_value = {"assistant_mode": "tater"}
        for error in (RuntimeError("TTS failed"), ClientError("TTS failed"), OSError("TTS failed")):
            with self.subTest(error=type(error).__name__):
                self.tater.async_synthesize.side_effect = error
                with self.assertRaisesRegex(RuntimeError, "TTS failed"):
                    await identify(self.manager, "kitchen")
        self.tater.store_clip.assert_not_called()
        self.announce.assert_not_awaited()

    async def test_ha_tts_and_playback_errors_reach_both_identify_callers(self):
        for error in (HomeAssistantError("No TTS engine"), RuntimeError("Playback failed")):
            with self.subTest(error=str(error)):
                self.announce.side_effect = error
                with self.assertRaisesRegex(RuntimeError, str(error)):
                    await identify(self.manager, "kitchen")

    async def test_identify_waits_for_announcement_and_preserves_cancellation(self):
        entered = asyncio.Event()
        finish = asyncio.Event()

        async def announce(**kwargs):
            entered.set()
            await finish.wait()

        self.announce.side_effect = announce
        task = asyncio.create_task(identify(self.manager, "kitchen"))
        await asyncio.wait_for(entered.wait(), timeout=1)
        self.assertFalse(task.done())
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task

    async def test_home_assistant_button_uses_the_same_identify_route(self):
        press = load_method("button.py", "TaterIdentifyButton", "async_press")
        self.manager.async_identify = AsyncMock()
        button = SimpleNamespace(
            runtime=SimpleNamespace(manager=self.manager, device_id="kitchen")
        )
        await press(button)
        self.manager.async_identify.assert_awaited_once_with("kitchen")

    async def test_panel_identify_endpoint_returns_success_after_playback(self):
        post = load_method(
            "http.py", "IdentifyView", "post", _manager=lambda request: self.manager
        )
        self.manager.async_identify = AsyncMock()
        view = SimpleNamespace(json=lambda body: body)
        self.assertEqual(await post(view, None, "kitchen"), {"ok": True})
        self.manager.async_identify.assert_awaited_once_with("kitchen")

    async def test_panel_identify_endpoint_reports_tts_or_playback_failure(self):
        class HTTPBadRequest(Exception):
            def __init__(self, *, text):
                super().__init__(text)

        post = load_method(
            "http.py", "IdentifyView", "post",
            _manager=lambda request: self.manager,
            web=SimpleNamespace(HTTPBadRequest=HTTPBadRequest),
        )
        self.manager.async_identify = AsyncMock(side_effect=RuntimeError("No TTS engine"))
        view = SimpleNamespace(json=Mock())
        with self.assertRaisesRegex(HTTPBadRequest, "No TTS engine"):
            await post(view, None, "kitchen")
        view.json.assert_not_called()


class AnnouncementPlaybackTests(unittest.IsolatedAsyncioTestCase):
    async def test_announcement_sends_url_and_waits_for_device_success_or_failure(self):
        play_url = load_method(
            "manager.py", "SatelliteRuntime", "async_play_url",
            asyncio=asyncio, contextlib=contextlib,
        )
        play_parts = load_method(
            "assist_satellite.py", "TaterAssistSatellite", "_play_announcement_parts"
        )
        for ok in (True, False):
            with self.subTest(ok=ok):
                sent = asyncio.Event()

                async def send(command, payload):
                    self.assertEqual(command, "play.url")
                    self.assertEqual(payload, {
                        "url": "http://ha.lan:8123/identify.wav",
                        "tts_kind": "announcement",
                    })
                    sent.set()
                    return True

                runtime = SimpleNamespace(
                    connected=True, name="Kitchen Echo",
                    playback_waiters=[], async_send=send,
                )
                runtime.async_play_url = lambda *args, **kwargs: play_url(
                    runtime, *args, **kwargs
                )
                entity = SimpleNamespace(runtime=runtime)
                announcement = SimpleNamespace(
                    preannounce_media_id=None,
                    media_id="http://ha.lan:8123/identify.wav",
                )
                task = asyncio.create_task(play_parts(entity, announcement, continue_after=False))
                await asyncio.wait_for(sent.wait(), timeout=1)
                self.assertFalse(task.done())
                self.assertEqual(len(runtime.playback_waiters), 1)
                runtime.playback_waiters[0].set_result(ok)
                if ok:
                    await task
                else:
                    with self.assertRaisesRegex(RuntimeError, "Playback failed"):
                        await task
                self.assertEqual(runtime.playback_waiters, [])


if __name__ == "__main__":
    unittest.main()
