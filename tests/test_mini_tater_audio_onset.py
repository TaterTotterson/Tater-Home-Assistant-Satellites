"""Keep command beginnings intact while the neural VAD initializes."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from test_tater_assistant import tater, _Manager


class AudioOnsetTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.runtime = tater.MiniTaterRuntime(_Manager())
        self.runtime.setup()
        self.events = []

    async def emit(self, name, data):
        self.events.append((name, data))

    @staticmethod
    async def stream(chunks):
        for chunk in chunks:
            yield chunk

    async def capture(self, chunks, backend):
        with patch.object(tater, "_create_vad_backend", return_value=backend):
            return [chunk async for chunk in self.runtime._voice_activity_stream(
                self.stream(chunks), {"rate": 16000, "width": 2, "channels": 1}, "default", self.emit,
            )]

    async def test_first_command_frame_is_sent_before_vad_has_any_score(self):
        # A new microVAD instance initially returns no score. It must not hold
        # the audio back from a streaming STT provider while it initializes.
        backend = SimpleNamespace(process=lambda data: None)
        source = self.stream([b"\x05\x00" * 160, b"\x06\x00" * 160])
        with patch.object(tater, "_create_vad_backend", return_value=backend):
            output = self.runtime._voice_activity_stream(source, {}, "default", self.emit)
            self.assertEqual(await asyncio.wait_for(anext(output), 0.5), b"\x05\x00" * 160)
            self.assertEqual(self.events, [])
            await output.aclose()
        self.assertEqual([name for name, data in self.events], ["STT_VAD_END"])

    async def test_late_neural_vad_preserves_every_initial_byte_in_order(self):
        class DelayedVad:
            frames = 0

            def process(self, data):
                self.frames += 1
                if self.frames <= 76:
                    return None
                return 0.9 if self.frames <= 110 else 0.0

        # Distinct samples make dropped, duplicated, or reordered frames clear.
        chunks = [index.to_bytes(2, "little") * 160 for index in range(250)]
        captured = await self.capture(chunks, DelayedVad())
        self.assertEqual(b"".join(captured), b"".join(chunks[:len(captured)]))
        self.assertGreater(len(captured), 110)
        self.assertLess(len(captured), len(chunks))
        self.assertEqual([name for name, data in self.events], ["STT_VAD_START", "STT_VAD_END"])

    async def test_short_command_still_reaches_stt_when_vad_never_accepts_it(self):
        chunks = [b"\x10\x00" * 160] * 30 + [b"\x00\x00" * 160] * 400
        captured = await self.capture(chunks, SimpleNamespace(process=lambda data: 0.0))
        self.assertEqual(captured[:30], chunks[:30])
        self.assertLess(len(captured), len(chunks))
        self.assertEqual([name for name, data in self.events], ["STT_VAD_END"])

    async def test_no_speech_timeout_sends_audio_stop_and_uses_provider_transcript(self):
        self.runtime.async_process_text = AsyncMock(return_value={
            "response": "Done.", "conversation_id": "onset-1",
        })
        self.runtime.async_synthesize = AsyncMock(return_value=("audio/wav", b"wave"))
        seen = []

        async def transcribe(stream, audio_format):
            seen.extend([chunk async for chunk in stream])
            return "Turn on the office lights"

        self.runtime.async_transcribe = transcribe
        satellite = SimpleNamespace(
            device_id="sat-1", server_base_url="http://ha.test",
            effective_settings=lambda: {"continued_chat": False},
        )
        chunks = [b"\x12\x00" * 160] * 30 + [b"\x00\x00" * 160] * 400
        with patch.object(tater, "_create_vad_backend", return_value=SimpleNamespace(process=lambda data: 0.0)):
            await self.runtime.async_run_voice(satellite, self.stream(chunks), {}, "", self.emit)
        self.assertEqual(seen[:30], chunks[:30])
        self.runtime.async_process_text.assert_awaited_once_with(
            "Turn on the office lights", conversation_id="", device_id="sat-1",
        )

    async def test_empty_transcript_never_reaches_hydra(self):
        self.runtime.async_transcribe = AsyncMock(return_value="")
        self.runtime.async_process_text = AsyncMock()
        satellite = SimpleNamespace(device_id="sat-1")
        with self.assertRaisesRegex(RuntimeError, "STT returned no speech"):
            await self.runtime.async_run_voice(satellite, self.stream([]), {}, "", self.emit)
        self.runtime.async_process_text.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
