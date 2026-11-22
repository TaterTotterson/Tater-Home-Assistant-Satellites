from __future__ import annotations

import asyncio
from enum import Enum
import json
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock

from test_tater_assistant import tater, _Manager
from test_identify import load_method


class MiniTaterFollowupTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.runtime = tater.MiniTaterRuntime(_Manager())
        self.runtime.setup()
        self.runtime.async_transcribe = AsyncMock(return_value="Turn on the light")
        self.runtime.async_process_text = AsyncMock(return_value={
            "response": "Which room should I use?", "conversation_id": "conversation-1",
            "continue_conversation": False,
        })
        self.runtime.async_synthesize = AsyncMock(return_value=("audio/wav", b"wave"))
        self.runtime._voice_activity_stream = lambda stream, *args: stream
        self.runtime._chat = AsyncMock(return_value={"content": '{"follow_up":true}'})
        self.satellite = SimpleNamespace(
            device_id="sat-1", server_base_url="http://ha.test:8123",
            effective_settings=lambda: {"continued_chat": True, "muted": False},
        )
        self.events = []

    async def voice(self, conversation_id=""):
        async def audio():
            yield b"audio"

        async def emit(name, data):
            self.events.append((name, data))

        await self.runtime.async_run_voice(self.satellite, audio(), {}, conversation_id, emit)
        return next(data for name, data in self.events if name == "INTENT_END")

    async def test_direct_question_sends_reopen_flag_and_preserves_conversation_for_next_turn(self):
        intent = await self.voice()
        self.assertTrue(intent["continue_conversation"])
        self.assertEqual(intent["conversation_id"], "conversation-1")
        self.assertEqual(intent["speech"], "Which room should I use?")
        self.runtime._chat.assert_awaited_once()
        self.assertFalse(self.runtime._chat.await_args.kwargs["tools"])
        self.assertEqual(self.runtime._chat.await_args.kwargs["role"], "hermes")
        self.assertEqual([name for name, _ in self.events][-3:], ["TTS_START", "TTS_END", "RUN_END"])
        self.events.clear()
        await self.voice(intent["conversation_id"])
        self.assertEqual(self.runtime.async_process_text.await_args.kwargs["conversation_id"], "conversation-1")

    async def test_disabled_or_muted_satellite_skips_classifier_and_keeps_mic_closed(self):
        for settings in ({"continued_chat": False}, {"continued_chat": True, "muted": True}):
            self.events.clear()
            self.satellite.effective_settings = lambda: settings
            intent = await self.voice()
            self.assertFalse(intent["continue_conversation"])
        self.runtime._chat.assert_not_awaited()
        self.assertEqual(self.runtime.async_synthesize.await_count, 2)

    async def test_statement_or_invalid_result_never_reopens_but_reply_still_plays(self):
        self.runtime.async_process_text.return_value["response"] = "The light is on."
        for value in (False, "true", 1, None):
            self.events.clear()
            self.runtime._chat.return_value = {"content": json.dumps({"follow_up": value})}
            intent = await self.voice()
            self.assertFalse(intent["continue_conversation"], value)
            self.assertIn("TTS_END", [name for name, _ in self.events])
        self.events.clear()
        self.runtime._chat.return_value = {"content": "not json"}
        self.assertFalse((await self.voice())["continue_conversation"])

    async def test_provider_error_keeps_reply_and_does_not_reopen(self):
        self.runtime._chat.side_effect = RuntimeError("model unavailable")
        intent = await self.voice()
        self.assertFalse(intent["continue_conversation"])
        self.runtime.async_synthesize.assert_awaited_once()
        self.assertEqual(self.events[-1][0], "RUN_END")

    async def test_slow_classifier_is_cancelled_after_bounded_wait(self):
        cancelled = asyncio.Event()

        async def never_reply(*args, **kwargs):
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        self.runtime._chat.side_effect = never_reply
        self.assertFalse(await asyncio.wait_for(self.runtime._response_is_followup_question("Which room?"), timeout=5))
        self.assertTrue(cancelled.is_set())


class HomeAssistantContinuationTests(unittest.IsolatedAsyncioTestCase):
    async def test_ha_agent_continuation_flag_is_forwarded_without_mini_tater_classification(self):
        event_types = Enum("PipelineEventType", "STT_END INTENT_PROGRESS INTENT_END TTS_START TTS_END ERROR")
        translate = load_method(
            "assist_satellite.py", "TaterAssistSatellite", "on_pipeline_event",
            PipelineEventType=event_types, _EVENT_NAMES={event_types.INTENT_END: "INTENT_END"},
            callback=lambda method: method,
        )
        for follow_up in (True, False):
            tasks = []
            entity = SimpleNamespace(
                _wake_candidate=None,
                hass=SimpleNamespace(async_create_task=Mock(side_effect=lambda coroutine, name: tasks.append(asyncio.create_task(coroutine)))),
                _async_forward_pipeline_event=AsyncMock(),
            )
            event = SimpleNamespace(type=event_types.INTENT_END, data={"intent_output": {
                "conversation_id": "ha-conversation", "continue_conversation": follow_up,
                "response": {"speech": {"plain": {"speech": "Which room?" if follow_up else "Done."}}},
            }})
            translate(entity, event)
            await asyncio.gather(*tasks)
            data = entity._async_forward_pipeline_event.await_args.args[1]
            self.assertEqual(data["continue_conversation"], follow_up)
            self.assertEqual(data["conversation_id"], "ha-conversation")


if __name__ == "__main__":
    unittest.main()
