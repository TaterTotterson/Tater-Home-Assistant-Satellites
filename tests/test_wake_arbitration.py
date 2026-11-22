"""Wake selection and transport behavior without a running Home Assistant."""

from __future__ import annotations

import ast
import asyncio
import contextlib
import importlib.util
import logging
from pathlib import Path
import struct
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock

COMPONENT = Path(__file__).resolve().parents[1] / "custom_components/tater_satellite"


def load_module(name, filename):
    spec = importlib.util.spec_from_file_location(name, COMPONENT / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


arbitration = load_module("bridge_wake_arbitration_tests", "wake_arbitration.py")
audio = load_module("bridge_wake_audio_tests", "wake_audio.py")


def load_methods(filename, classname, names, **scope):
    tree = ast.parse((COMPONENT / filename).read_text())
    cls = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == classname
    )
    cls.body = [node for node in cls.body if getattr(node, "name", "") in names]
    cls.bases = []
    cls.decorator_list = []
    scope.update(
        {
            "asyncio": asyncio,
            "contextlib": contextlib,
            "callback": lambda method: method,
        }
    )
    exec(compile(ast.Module(body=[cls], type_ignores=[]), filename, "exec"), scope)
    return scope[classname]


def pcm(level, samples=1600):
    return struct.pack("<h", level) * samples


class ArbitrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.arbiter = arbitration.WakeArbitrator()
        self.settings = {
            **arbitration.DEFAULT_SETTINGS,
            "window_ms": 100,
            "release_ms": 0,
        }

    async def asyncTearDown(self):
        self.arbiter.shutdown()
        self.assertEqual(self.arbiter.snapshot()["pending"], 0)
        self.assertEqual(self.arbiter.snapshot()["busy"], 0)

    def start(self, device, room="Office", phrase="hey_tater", **settings):
        return self.arbiter.begin(
            device,
            device,
            room,
            phrase,
            {**self.settings, **settings},
            {"rate": 16000, "width": 2, "channels": 1},
        )

    async def test_stronger_command_wins_even_when_it_wakes_second(self):
        first = self.start("far")
        second = self.start("near", phrase="Hey Tater", room="office")
        first.add_audio(pcm(400))
        second.add_audio(pcm(4000))
        self.assertFalse(await first.decision)
        self.assertTrue(await second.decision)
        snapshot = self.arbiter.snapshot()
        self.assertEqual(snapshot["history"][0]["winner_id"], "near")
        self.assertEqual(snapshot["busy"], 1)

    async def test_first_wake_option_and_missing_or_silent_audio_are_deterministic(
        self,
    ):
        for selection, provide_audio in (
            ("first_wake", True),
            ("strongest_audio", False),
        ):
            first = self.start("first", selection=selection)
            second = self.start("second", selection=selection)
            if provide_audio:
                second.add_audio(pcm(30000))
            self.assertTrue(await first.decision)
            self.assertFalse(await second.decision)
            self.arbiter.cancel(first)
            self.arbiter.cancel(second)

    async def test_rooms_are_independent_but_whole_home_competes(self):
        office = self.start("office")
        kitchen = self.start("kitchen", room="Kitchen")
        self.assertEqual(
            await asyncio.gather(office.decision, kitchen.decision), [True, True]
        )
        self.arbiter.cancel(office)
        self.arbiter.cancel(kitchen)
        office = self.start("office", scope="global")
        kitchen = self.start("kitchen", room="Kitchen", scope="global")
        self.assertEqual(
            await asyncio.gather(office.decision, kitchen.decision), [True, False]
        )

    async def test_missing_rooms_compete_and_other_phrases_do_not_interrupt_busy_room(
        self,
    ):
        first = self.start("one", room="")
        second = self.start("two", room="  ")
        self.assertEqual(
            await asyncio.gather(first.decision, second.decision), [True, False]
        )
        late = self.start("late", room="", phrase="hey_jarvis")
        self.assertFalse(await late.decision)
        self.assertEqual(self.arbiter.snapshot()["history"][0]["reason"], "busy")

    async def test_simultaneous_different_phrases_still_protect_one_busy_room(self):
        first = self.start("one")
        second = self.start("two", phrase="hey_jarvis")
        self.assertEqual(
            await asyncio.gather(first.decision, second.decision), [True, False]
        )

    async def test_release_grace_owner_rewake_and_stale_completion(self):
        first = self.start("one", release_ms=500)
        self.assertTrue(await first.decision)
        self.arbiter.release(first)
        self.assertFalse(await self.start("other").decision)
        followup = self.start("one", phrase="")
        self.assertTrue(await followup.decision)
        self.arbiter.cancel(first)  # stale cleanup must not clear the new owner
        self.arbiter.release(first)
        self.assertFalse(await self.start("late").decision)
        self.arbiter.release(followup)
        self.assertTrue(await self.start("other").decision)

    async def test_abort_pending_winner_disconnect_and_timeout_release(self):
        first = self.start("one")
        other = self.start("two")
        self.arbiter.cancel(first)
        self.assertFalse(await first.decision)
        self.assertTrue(await other.decision)
        # Exercise expiration without waiting the minimum five real seconds.
        other.expires = asyncio.get_running_loop().time() - 1
        third = self.start("three")
        self.assertTrue(await third.decision)
        self.arbiter.cancel(third)
        fourth = self.start("four")
        self.assertTrue(await fourth.decision)

    async def test_disabling_and_manual_followups_do_not_wait_or_suppress(self):
        pending = self.start("one")
        disabled = self.start("two", enabled=False)
        button = self.start("button", room="Other room", phrase="")
        self.assertTrue(disabled.decision.done())
        self.assertTrue(await disabled.decision)
        self.assertTrue(await button.decision)
        # Settings changes apply to future wakes, without interrupting this one.
        self.assertTrue(await pending.decision)

    async def test_scoring_is_packet_independent_and_bounded(self):
        full = self.start("full")
        split = self.start("split")
        data = pcm(5000, 2000) + pcm(100, 1000)
        full.add_audio(data)
        for index in range(0, len(data), 37):
            split.add_audio(data[index : index + 37])
        self.assertAlmostEqual(full.dbfs, split.dbfs)
        split.add_audio(pcm(2000, 100000))
        self.assertEqual(split.samples, split.sample_limit)
        self.assertLessEqual(len(split.tail), 1)

    async def test_cancel_all_cleans_timers_and_history_is_bounded(self):
        for index in range(40):
            winner = self.start("winner", phrase="")
            self.assertFalse(await self.start(f"late{index}").decision)
            self.arbiter.cancel(winner)
        self.assertEqual(len(self.arbiter.snapshot()["history"]), 30)
        pending = self.start("pending")
        self.arbiter.shutdown()
        self.assertFalse(await pending.decision)


class SettingsTests(unittest.IsolatedAsyncioTestCase):
    async def test_settings_persist_without_mutating_or_pushing_firmware_settings(self):
        cls = load_methods(
            "manager.py",
            "TaterSatelliteManager",
            {
                "wake_arbitration_settings",
                "async_set_wake_arbitration_settings",
            },
            normalize_arbitration_settings=arbitration.normalize_settings,
        )
        manager = cls()
        manager.data = {
            "global_settings": {"volume": 0.7},
            "devices": {"one": {"settings": {"wake_word": "hey_tater"}}},
        }
        manager.async_save = AsyncMock()
        saved = await manager.async_set_wake_arbitration_settings(
            {"window_ms": 1200, "scope": "global"}
        )
        self.assertEqual(saved["window_ms"], 1200)
        self.assertEqual(saved["scope"], "global")
        self.assertEqual(manager.data["global_settings"], {"volume": 0.7})
        manager.async_save.assert_awaited_once()
        for bad in (
            {"volume": 1},
            {"window_ms": 99},
            {"window_ms": True},
            {"enabled": "false"},
            {"scope": "invalid"},
            {"release_ms": -1},
            {"busy_timeout_s": float("nan")},
            [],
            {"window_ms": 100.5},
        ):
            with self.assertRaises(ValueError, msg=str(bad)):
                await manager.async_set_wake_arbitration_settings(bad)
            self.assertEqual(manager.data["wake_arbitration"], saved)


class TransportTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.arbiter = arbitration.WakeArbitrator()
        self.tasks = []
        self.calls = []
        self.settings = {
            **arbitration.DEFAULT_SETTINGS,
            "window_ms": 100,
            "release_ms": 0,
        }
        self.entity_cls = load_methods(
            "assist_satellite.py",
            "TaterAssistSatellite",
            {
                "_audio_stream",
                "_run_pipeline",
                "async_device_voice_start",
                "device_audio",
                "device_audio_boundary",
                "async_device_voice_stop",
                "_async_forward_pipeline_event",
                "voice_playback_finished",
                "_queue_command_audio",
            },
            _LOGGER=logging.getLogger("arbitration-test"),
            _STATE_BY_EVENT={"STT_START": "listening", "TTS_END": "speaking"},
            _PLAYBACK_COMMAND_SETTLE_SECONDS=0,
            _ARBITRATION_BUFFER_BYTES=256 * 1024,
            PipelineStage=SimpleNamespace(STT="stt", TTS="tts"),
        )

    async def asyncTearDown(self):
        for task in self.tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        self.arbiter.shutdown()

    def entity(self, name, mode="home_assistant"):
        entity = self.entity_cls()
        queue = asyncio.Queue(maxsize=256)
        runtime = SimpleNamespace(
            device_id=name,
            name=name,
            room="Office",
            audio_queue=queue,
            add_audio=queue.put_nowait,
            finish_audio=lambda: queue.put_nowait(None),
            async_send=AsyncMock(return_value=True),
            add_log=Mock(),
            capabilities={},
        )

        def reset():
            while not queue.empty():
                queue.get_nowait()

        def spawn(hass, coroutine, name):
            task = asyncio.create_task(coroutine, name=name)
            self.tasks.append(task)
            return task

        runtime.reset_audio = reset
        entity.runtime = runtime
        entity.hass = object()
        entity.manager = SimpleNamespace(
            wake_arbitrator=self.arbiter,
            wake_arbitration_settings=lambda: dict(self.settings),
            tater_assistant=SimpleNamespace(settings=lambda: {"assistant_mode": mode}),
        )
        entity.config_entry = SimpleNamespace(async_create_background_task=spawn)
        entity._bridge_task = None
        entity._wake_candidate = None
        entity._accept_audio = False
        entity._response_playback_pending = False
        entity._arbitration_audio = bytearray()
        entity._arbitration_buffer_full = False
        entity._wake_preroll_gate = audio.WakePrerollGate()
        entity._pipeline_event_lock = asyncio.Lock()
        entity._conversation_display = SimpleNamespace(
            pipeline_event=lambda *args: None
        )
        entity._cancel_running_pipeline = AsyncMock()

        async def ha_pipeline(**kwargs):
            chunks = [chunk async for chunk in kwargs["audio_stream"]]
            self.calls.append((mode, name, chunks, kwargs["wake_word_phrase"]))
            await entity._async_forward_pipeline_event(
                "RUN_END", {}, entity._wake_candidate
            )

        async def mini_pipeline(runtime, stream, audio_format, conversation_id, emit):
            chunks = [chunk async for chunk in stream]
            self.calls.append((mode, name, chunks, conversation_id))
            await emit("RUN_END", {})

        entity.async_accept_pipeline_from_satellite = ha_pipeline
        entity.manager.tater_assistant.async_run_voice = mini_pipeline
        return entity

    async def test_ack_is_immediate_both_modes_keep_first_words_only_winner_runs(self):
        for mode in ("home_assistant", "tater"):
            self.calls.clear()
            first, second = self.entity("far", mode), self.entity("near", mode)
            payload = {
                "wake_word": "hey_tater",
                "wake_preroll_boundary": 1,
                "conversation_id": "chat-id",
                "audio_format": {"rate": 16000, "width": 2, "channels": 1},
            }
            for entity, level in ((first, 100), (second, 2000)):
                self.assertTrue(await entity.async_device_voice_start(payload))
                self.assertFalse(entity._wake_candidate.decision.done())
                entity.device_audio(
                    pcm(30000)
                )  # wake-word pre-roll must not affect the winner
                entity.device_audio_boundary({"kind": "wake_preroll_end", "version": 1})
                entity.device_audio(
                    pcm(level)
                )  # first word arrives after the immediate ack
                entity.device_audio(pcm(level * 2))
                await entity.async_device_voice_stop({"abort": False})
            await asyncio.gather(*self.tasks)
            self.assertEqual(len(self.calls), 1)
            called_mode, name, chunks, context = self.calls[0]
            self.assertEqual(
                (called_mode, name, context),
                (mode, "near", "chat-id" if mode == "tater" else "hey tater"),
            )
            self.assertEqual(b"".join(chunks), pcm(2000) + pcm(4000))
            self.assertIn(
                ("voice.event", {"event": "RUN_END", "data": {}}),
                [call.args for call in first.runtime.async_send.call_args_list],
            )
            self.assertFalse(
                any(
                    call.args[0] == "play.url"
                    for call in first.runtime.async_send.call_args_list
                )
            )
            remaining = first.runtime.audio_queue.qsize()
            first.device_audio(
                pcm(1000)
            )  # late packets must not fill a discarded queue
            self.assertEqual(first.runtime.audio_queue.qsize(), remaining)
            while not first.runtime.audio_queue.empty():
                self.assertIsNone(first.runtime.audio_queue.get_nowait())
            self.arbiter.shutdown()

    async def test_cancellation_before_selection_never_starts_pipeline_and_allows_next_wake(
        self,
    ):
        entity = self.entity("one")
        await entity.async_device_voice_start({"wake_word": "hey_tater"})
        await asyncio.sleep(0)
        await entity.async_device_voice_stop({"abort": True})
        self.assertEqual(self.calls, [])
        self.assertEqual(self.arbiter.snapshot()["pending"], 0)
        await entity.async_device_voice_start({"wake_word": "hey_tater"})
        task = entity._bridge_task
        entity.device_audio(pcm(1000))
        await entity.async_device_voice_stop({})
        await task
        self.assertEqual(len(self.calls), 1)

    async def test_claim_lasts_through_playback_errors_release_and_old_events_do_not_touch_new_turn(
        self,
    ):
        entity = self.entity("one")
        await entity.async_device_voice_start({"wake_word": ""})
        await entity.async_device_voice_stop({})
        await asyncio.gather(*self.tasks)
        old = entity._wake_candidate
        # Start a fresh claim, as if the pipeline is now producing TTS.
        await entity.async_device_voice_start({"wake_word": ""})
        current = entity._wake_candidate
        await entity._async_forward_pipeline_event(
            "TTS_END", {"url": "/reply.wav"}, current
        )
        await entity._async_forward_pipeline_event("RUN_END", {}, current)
        self.assertEqual(self.arbiter.snapshot()["busy"], 1)
        busy = self.arbiter.begin(
            "other", "other", "Office", "hey_tater", self.settings, {}
        )
        self.assertFalse(await busy.decision)
        await entity._async_forward_pipeline_event("ERROR", {}, old)
        self.assertEqual(self.arbiter.snapshot()["busy"], 1)
        entity.voice_playback_finished()  # both successful and failed playback call this hook
        self.assertEqual(self.arbiter.snapshot()["busy"], 0)

    async def test_small_packets_exceeding_live_queue_capacity_keep_every_first_word(
        self,
    ):
        entity = self.entity("one")
        await entity.async_device_voice_start({"wake_word": "hey_tater"})
        expected = b"".join(pcm(index, 80) for index in range(600))
        for offset in range(0, len(expected), 160):
            entity.device_audio(expected[offset : offset + 160])
        await entity.async_device_voice_stop({})
        await entity._bridge_task
        self.assertEqual(b"".join(self.calls[0][2]), expected)

    async def test_provider_failure_releases_the_room_in_both_modes(self):
        for mode in ("home_assistant", "tater"):
            entity = self.entity("one", mode)
            failure = AsyncMock(side_effect=RuntimeError("provider unavailable"))
            if mode == "tater":
                entity.manager.tater_assistant.async_run_voice = failure
            else:
                entity.async_accept_pipeline_from_satellite = failure
            await entity.async_device_voice_start({"wake_word": ""})
            with self.assertLogs("arbitration-test", level="ERROR"):
                await entity._bridge_task
            self.assertFalse(entity._accept_audio)
            self.assertEqual(self.arbiter.snapshot()["busy"], 0)
            self.assertTrue(
                any(
                    call.args[0] == "voice.event" and call.args[1]["event"] == "ERROR"
                    for call in entity.runtime.async_send.call_args_list
                )
            )


if __name__ == "__main__":
    unittest.main()
