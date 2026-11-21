"""Doorbell triggers, isolated outputs, and HA/Mini-Tater speech routing."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import sys
import time
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "tater_doorbell_tests"
package = ModuleType(PACKAGE)
package.__path__ = [str(ROOT / "custom_components/tater_satellite")]
sys.modules[PACKAGE] = package
SPEC = importlib.util.spec_from_file_location(f"{PACKAGE}.doorbell", Path(package.__path__[0]) / "doorbell.py")
doorbell = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = doorbell
SPEC.loader.exec_module(doorbell)
KEY = "a" * 32


def state(entity_id, value="idle", **attributes):
    return SimpleNamespace(entity_id=entity_id, state=value, attributes=attributes, name=attributes.get("friendly_name", entity_id))


def config(**changes):
    return {"name": "Front door", "camera_entity": "camera.porch", "trigger_entity": "event.press",
            "trigger_value": "event:press", "speaker_entity": "media_player.other_brand", "screens": ["rook"], **changes}


class NormalizeTests(unittest.TestCase):
    def test_independent_targets_and_prompt_defaults(self):
        row = doorbell.normalize_doorbell(config(screens=["rook", "rook"]))
        self.assertEqual(row["speaker_entity"], "media_player.other_brand")
        self.assertEqual(row["screens"], ["rook"])
        self.assertEqual(row["prompt"], doorbell.DEFAULT_PROMPT)

    def test_invalid_targets_and_unbounded_settings_rejected(self):
        for change in ({"speaker_entity": "light.porch"}, {"speaker_entity": ""},
                       {"screens": "rook"}, {"screens": ["../rook"]},
                       {"greeting_enabled": False, "screens": []},
                       {"display_seconds": 0}, {"display_seconds": 301}, {"cooldown_seconds": -1},
                       {"camera_entity": "sensor.camera"}, {"trigger_value": "event:"}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                doorbell.normalize_doorbell(config(**change))


class DoorbellTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.states = {"camera.porch": state("camera.porch"),
                       "event.press": state("event.press", "unknown"),
                       "media_player.other_brand": state("media_player.other_brand", supported_features=512),
                       "media_player.video_only": state("media_player.video_only", supported_features=16384)}
        self.listeners = []
        modules = {}
        for name in ("homeassistant", "homeassistant.core", "homeassistant.helpers", "homeassistant.helpers.event",
                     "homeassistant.helpers.entity_registry", "homeassistant.components", "homeassistant.components.assist_pipeline",
                     "homeassistant.components.tts", "homeassistant.components.tts.media_source"):
            modules[name] = ModuleType(name)
        modules["homeassistant.core"].callback = lambda fn: fn
        def listen(hass, entities, callback):
            row = SimpleNamespace(entities=set(entities), callback=callback, unsubscribed=False)
            self.listeners.append(row)
            return lambda: setattr(row, "unsubscribed", True)
        modules["homeassistant.helpers.event"].async_track_state_change_event = listen
        modules["homeassistant.helpers.entity_registry"].async_get = lambda hass: SimpleNamespace(async_get=lambda entity_id: None)
        self.tts_audio = AsyncMock(return_value=("wav", b"ha-tts"))
        self.tts_source = Mock(return_value="media-source://tts/selected")
        modules["homeassistant.components.tts"].async_get_media_source_audio = self.tts_audio
        modules["homeassistant.components.tts.media_source"].generate_media_source_id = self.tts_source
        modules["homeassistant.components.assist_pipeline"].async_get_pipeline = lambda hass: SimpleNamespace(
            tts_engine="tts.home_voice", tts_language="en", tts_voice="chosen_voice")
        self.patch = patch.dict(sys.modules, modules)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.hass = SimpleNamespace(states=SimpleNamespace(get=self.states.get,
            async_all=lambda domain: [row for row in self.states.values() if row.entity_id.startswith(domain + ".")]),
            services=SimpleNamespace(async_call=AsyncMock()))
        self.voice = SimpleNamespace(settings=lambda: {"assistant_mode": "home_assistant"},
            _describe_images=AsyncMock(return_value="Hello! You can leave that parcel by the door."),
            async_synthesize=AsyncMock(return_value=("audio/wav", b"mini-tts")), store_clip=Mock(return_value="clip-id"))
        self.manager = SimpleNamespace(hass=self.hass, data={}, tater_assistant=self.voice,
            entry=SimpleNamespace(async_create_background_task=lambda hass, coro, name: asyncio.create_task(coro, name=name)),
            runtimes={"rook": SimpleNamespace(device_id="rook", name="Rook", connected=True,
                capabilities={"screen_cameras": True, "screen_camera_popup_version": 1})},
            awareness=SimpleNamespace(catalog=lambda: {"cameras": [], "triggers": []}),
            display_panels=SimpleNamespace(async_show_doorbell=AsyncMock()),
            public_base_url=lambda: "http://ha.test", async_save=AsyncMock())
        self.runtime = doorbell.DoorbellCoordinator(self.manager)
        await self.runtime.async_start()
        self.addAsyncCleanup(self.runtime.async_shutdown)
        self.capture = AsyncMock(return_value=(b"jpeg-at-trigger", "image/jpeg"))
        self.capture_patch = patch.object(doorbell, "capture_camera_image", self.capture)
        self.capture_patch.start()
        self.addCleanup(self.capture_patch.stop)

    async def save(self, **changes):
        return await self.runtime.async_save_doorbell(config(**changes))

    def press(self, before="unknown", after=None):
        self.listeners[-1].callback(SimpleNamespace(data={"entity_id": "event.press",
            "old_state": state("event.press", before),
            "new_state": state("event.press", after or datetime.now(timezone.utc).isoformat(), event_type="press")}))

    async def test_any_brand_player_uses_ha_default_pipeline_voice(self):
        row = await self.save(prompt="Mention a clearly visible package.")
        result = await self.runtime.async_test(row["id"])
        self.assertEqual(result["status"], "sent")
        self.tts_source.assert_called_once_with(self.hass, result["greeting"], engine="tts.home_voice", language="en", options={"voice": "chosen_voice"})
        self.tts_audio.assert_awaited_once()
        self.voice.store_clip.assert_called_once_with("audio/wav", b"ha-tts")
        self.voice.async_synthesize.assert_not_awaited()
        call = self.hass.services.async_call.await_args
        self.assertEqual(call.args[:2], ("media_player", "play_media"))
        self.assertEqual(call.args[2]["entity_id"], "media_player.other_brand")
        self.assertEqual(call.args[2]["media_content_type"], "audio/wav")
        self.assertEqual(call.args[2]["media_content_id"], "http://ha.test/api/tater/satellite/v1/tater/audio/clip-id")
        self.assertNotIn("announce", call.args[2])
        prompt, images = self.voice._describe_images.await_args.args
        self.assertIn("Mention a clearly visible package.", prompt)
        self.assertIn("directly to the visitor", prompt)
        self.assertTrue(images[0]["data_url"].startswith("data:image/jpeg;base64,"))

    async def test_mini_tater_uses_existing_tts_settings(self):
        self.voice.settings = lambda: {"assistant_mode": "tater"}
        self.states["media_player.other_brand"].attributes["supported_features"] |= doorbell.MEDIA_ANNOUNCE
        row = await self.save(screens=[])
        result = await self.runtime.async_test(row["id"])
        self.assertEqual(result["status"], "sent")
        self.voice.async_synthesize.assert_awaited_once_with(result["greeting"])
        self.tts_audio.assert_not_awaited()
        self.assertTrue(self.hass.services.async_call.await_args.args[2]["announce"])

    async def test_screens_open_while_vision_waits_and_survive_failure(self):
        started = asyncio.Event()
        async def vision(*args):
            started.set()
            await asyncio.sleep(0.01)
            self.manager.display_panels.async_show_doorbell.assert_awaited_once()
            raise RuntimeError("Vision is offline")
        self.voice._describe_images.side_effect = vision
        row = await self.save()
        result = await self.runtime.async_test(row["id"])
        self.assertTrue(started.is_set())
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["deliveries"][0]["status"], "sent")
        self.assertIn("Vision is offline", result["deliveries"][1]["error"])
        self.hass.services.async_call.assert_not_awaited()

    async def test_screen_only_does_not_need_vision_or_tts(self):
        row = await self.save(greeting_enabled=False, speaker_entity="")
        self.assertEqual((await self.runtime.async_test(row["id"]))["status"], "sent")
        self.capture.assert_not_awaited()
        self.voice._describe_images.assert_not_awaited()
        self.tts_audio.assert_not_awaited()

    async def test_offline_screen_does_not_stop_other_outputs(self):
        row = await self.save()
        self.manager.runtimes["rook"].connected = False
        result = await self.runtime.async_test(row["id"])
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["deliveries"][0]["error"], "This screen is offline")
        self.hass.services.async_call.assert_awaited_once()

    async def test_capture_or_empty_vision_failure_never_speaks(self):
        row = await self.save()
        for source in ("capture", "empty"):
            with self.subTest(source=source):
                self.capture.side_effect = RuntimeError("Camera is offline") if source == "capture" else None
                self.voice._describe_images.return_value = ""
                result = await self.runtime.async_test(row["id"])
                self.assertEqual(result["status"], "partial")
                self.hass.services.async_call.assert_not_awaited()

    async def test_press_edges_cooldown_pause_and_restart(self):
        row = await self.save()
        self.press(after="2000-01-01T00:00:00+00:00")
        self.assertFalse(self.runtime._tasks)
        self.press()
        await asyncio.gather(*self.runtime._tasks.values())
        self.press()
        self.assertFalse(self.runtime._tasks)
        await self.runtime.async_shutdown()
        restarted = doorbell.DoorbellCoordinator(self.manager)
        await restarted.async_start()
        self.addAsyncCleanup(restarted.async_shutdown)
        self.assertGreater(restarted._last_started[row["id"]], time.time() - 10)
        await restarted.async_save_doorbell(config(enabled=False), row["id"])
        self.assertTrue(self.listeners[-1].unsubscribed)

    async def test_deleting_inflight_vision_cancels_greeting(self):
        started = asyncio.Event()
        async def blocked(*args):
            started.set()
            await asyncio.Event().wait()
        self.voice._describe_images.side_effect = blocked
        row = await self.save()
        task = self.runtime._start(row, test=False)
        await started.wait()
        await self.runtime.async_delete_doorbell(row["id"])
        self.assertTrue(task.cancelled())
        self.hass.services.async_call.assert_not_awaited()
        self.assertNotIn(row["id"], self.runtime.doorbells)

    async def test_catalog_lists_generic_players_and_marks_old_screen_firmware(self):
        self.manager.runtimes["rook"].capabilities.pop("screen_camera_popup_version")
        snapshot = self.runtime.snapshot()
        self.assertEqual([row["id"] for row in snapshot["catalog"]["speakers"]], ["media_player.other_brand"])
        self.assertFalse(snapshot["catalog"]["screens"][0]["supported"])
        with self.assertRaisesRegex(ValueError, "Update"):
            await self.save()
        with self.assertRaisesRegex(ValueError, "does not support"):
            await self.save(screens=[], speaker_entity="media_player.video_only")

    async def test_history_is_bounded_and_test_does_not_enable_doorbell(self):
        row = await self.save(enabled=False)
        self.manager.data["doorbell_history"] = [{"id": str(i)} for i in range(50)]
        await self.runtime.async_test(row["id"])
        self.assertEqual(len(self.runtime.history), 50)
        self.assertFalse(self.runtime.doorbells[row["id"]]["enabled"])


if __name__ == "__main__":
    unittest.main()
