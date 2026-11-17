"""Wake-check wait validation and transport headroom without a running HA."""

from __future__ import annotations

import ast
import asyncio
from collections.abc import AsyncGenerator
import hashlib
from pathlib import Path
import re
import time
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock

COMPONENT = Path(__file__).resolve().parents[1] / "custom_components/tater_satellite"


def verifier_scope():
    tree = ast.parse((COMPONENT / "wake_verifier.py").read_text())
    names = {
        "DEFAULT_MATCH_THRESHOLD",
        "DEFAULT_TIMEOUT_MS",
        "_TRANSPORT_ALLOWANCE_MS",
        "_PCM_CHUNK_BYTES",
        "WakeVerifierUnavailable",
        "normalize_phrase",
        "transcript_match_score",
        "async_verify_packet",
        "_async_transcribe",
        "_pcm_stream",
    }
    nodes = [
        node
        for node in tree.body
        if getattr(node, "name", "") in names
        or (
            isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id in names
                for target in node.targets
            )
        )
    ]
    import difflib

    scope = {
        "asyncio": asyncio,
        "hashlib": hashlib,
        "re": re,
        "time": time,
        "difflib": difflib,
        "Any": object,
        "AsyncGenerator": AsyncGenerator,
        "HomeAssistant": object,
        "text": lambda value: str(value or "").strip(),
        "parse_wake_verifier_packet": lambda data: {
            "request_id": 1,
            "pcm": b"audio",
            "enforce": True,
            "sample_count": 16000,
        },
    }
    exec(
        compile(ast.Module(body=nodes, type_ignores=[]), "<wake verifier>", "exec"),
        scope,
    )
    return scope


def settings_action():
    tree = ast.parse((COMPONENT / "manager.py").read_text())
    cls = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "TaterSatelliteManager"
    )
    method = next(
        node
        for node in cls.body
        if getattr(node, "name", "") == "async_set_wake_verifier_settings"
    )
    scope = {
        "Any": object,
        "text": lambda value: str(value or "").strip(),
        "WAKE_VERIFIER_SETTING_KEYS": {
            "wake_verifier_mode",
            "wake_verifier_threshold",
            "wake_verifier_window_ms",
            "wake_verifier_timeout_ms",
        },
    }
    exec(
        compile(
            ast.Module(body=[method], type_ignores=[]), "<verifier settings>", "exec"
        ),
        scope,
    )
    return scope[method.name]


class WakeVerificationTests(unittest.IsolatedAsyncioTestCase):
    async def test_wait_save_validates_and_forwards_only_the_requested_settings(self):
        save = settings_action()
        group = AsyncMock(return_value={"saved": True})
        manager = SimpleNamespace(_async_set_global_setting_group=group)
        for timeout in (500, 1000, 1500, 2000):
            await save(
                manager,
                {"wake_verifier_mode": "enforce", "wake_verifier_timeout_ms": timeout},
            )
            self.assertEqual(
                group.call_args.args[0],
                {
                    "wake_verifier_mode": "enforce",
                    "wake_verifier_timeout_ms": timeout,
                },
            )
            self.assertIn(
                "wake_verifier_timeout_ms", group.call_args.kwargs["allowed_keys"]
            )
        group.reset_mock()
        for timeout in (
            None,
            True,
            -1,
            499,
            2001,
            "invalid",
            1000.5,
            float("nan"),
            float("inf"),
        ):
            with self.subTest(timeout=timeout), self.assertRaisesRegex(
                ValueError, "500 and 2000"
            ):
                await save(
                    manager,
                    {
                        "wake_verifier_mode": "enforce",
                        "wake_verifier_timeout_ms": timeout,
                    },
                )
        group.assert_not_awaited()
        await save(manager, {"wake_verifier_mode": "observe"})
        self.assertNotIn("wake_verifier_timeout_ms", group.call_args.args[0])

    async def test_audio_window_saves_independently_and_validates_before_saving(self):
        save = settings_action()
        group = AsyncMock(return_value={"saved": True})
        manager = SimpleNamespace(_async_set_global_setting_group=group)
        for window in (500, 1000, 1500, 2000):
            await save(
                manager,
                {
                    "wake_verifier_mode": "enforce",
                    "wake_verifier_window_ms": window,
                },
            )
            self.assertEqual(
                group.call_args.args[0],
                {
                    "wake_verifier_mode": "enforce",
                    "wake_verifier_window_ms": window,
                },
            )
            self.assertIn(
                "wake_verifier_window_ms", group.call_args.kwargs["allowed_keys"]
            )
            self.assertNotIn("wake_verifier_timeout_ms", group.call_args.args[0])
        group.reset_mock()
        for window in (
            None,
            True,
            -1,
            499,
            2001,
            "invalid",
            1000.5,
            float("nan"),
            float("inf"),
        ):
            with self.subTest(window=window), self.assertRaisesRegex(
                ValueError, "Verification audio window"
            ):
                await save(
                    manager,
                    {
                        "wake_verifier_mode": "enforce",
                        "wake_verifier_window_ms": window,
                    },
                )
        group.assert_not_awaited()
        await save(
            manager,
            {
                "wake_verifier_mode": "observe",
                "wake_verifier_window_ms": 2000,
                "wake_verifier_timeout_ms": 1000,
            },
        )
        self.assertEqual(
            group.call_args.args[0],
            {
                "wake_verifier_mode": "observe",
                "wake_verifier_window_ms": 2000,
                "wake_verifier_timeout_ms": 1000,
            },
        )

    async def test_empty_provider_result_keeps_allowing_listening(self):
        scope = verifier_scope()
        # Exercise the real transcription adapter, including SUCCESS with no
        # text, rather than replacing it with an assumed unavailable result.
        scope["async_get_pipeline"] = Mock(
            return_value=SimpleNamespace(
                stt_engine="stt.parakeet",
                stt_language="en",
                language="en",
                id="pipeline",
                name="Test",
            )
        )
        scope["PipelineNotFound"] = type("PipelineNotFound", (Exception,), {})
        engine = SimpleNamespace(
            check_metadata=Mock(return_value=True),
            async_process_audio_stream=AsyncMock(
                return_value=SimpleNamespace(
                    result="success",
                    text="",
                )
            ),
        )
        scope["stt"] = SimpleNamespace(
            async_get_speech_to_text_engine=Mock(return_value=engine),
            SpeechMetadata=lambda **kwargs: SimpleNamespace(**kwargs),
            AudioFormats=SimpleNamespace(WAV="wav"),
            AudioCodecs=SimpleNamespace(PCM="pcm"),
            AudioBitRates=SimpleNamespace(BITRATE_16=16),
            AudioSampleRates=SimpleNamespace(SAMPLERATE_16000=16000),
            AudioChannels=SimpleNamespace(CHANNEL_MONO=1),
            SpeechResultState=SimpleNamespace(SUCCESS="success"),
        )
        for mode in ("observe", "enforce"):
            result = await scope["async_verify_packet"](
                None,
                b"packet",
                pipeline_id="pipeline",
                phrase="Hey Tater",
                mode=mode,
            )
            self.assertTrue(result["accepted"])
            self.assertFalse(result["available"])
            self.assertEqual(result["reason"], "stt_no_text_fail_open")

    async def test_longer_wait_reserves_transport_time_and_preserves_mismatch_rejection(
        self,
    ):
        scope = verifier_scope()
        scope["_async_transcribe"] = AsyncMock(
            return_value=("Hey tutor", "pipeline", "Tater", "stt.whisper")
        )
        real_wait_for = asyncio.wait_for
        wait = AsyncMock()

        async def checked_wait(awaitable, *, timeout):
            return await real_wait_for(awaitable, timeout=timeout)

        wait.side_effect = checked_wait
        scope["asyncio"] = SimpleNamespace(wait_for=wait)
        result = await scope["async_verify_packet"](
            None,
            b"packet",
            pipeline_id="pipeline",
            phrase="Hey Tater",
            mode="enforce",
            timeout_ms=1000,
        )
        self.assertEqual(wait.call_args.kwargs["timeout"], 0.75)
        self.assertEqual(result["timeout_ms"], 1000)
        self.assertEqual(result["stt_budget_ms"], 750)
        self.assertFalse(result["accepted"])
        self.assertTrue(result["available"])
        self.assertEqual(result["reason"], "transcript_mismatch")

    async def test_timeout_is_reported_as_unavailable_without_disabling_listening(self):
        scope = verifier_scope()
        scope["_async_transcribe"] = AsyncMock(side_effect=TimeoutError)
        result = await scope["async_verify_packet"](
            None,
            b"packet",
            pipeline_id="pipeline",
            phrase="Hey Tater",
            mode="enforce",
            timeout_ms=500,
        )
        self.assertEqual(result["stt_budget_ms"], 250)
        self.assertEqual(result["stt_ms"], 250)
        self.assertTrue(result["accepted"])
        self.assertFalse(result["available"])
        self.assertEqual(result["reason"], "server_timeout_fail_open")


if __name__ == "__main__":
    unittest.main()
