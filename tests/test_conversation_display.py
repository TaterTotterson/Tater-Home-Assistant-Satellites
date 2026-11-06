from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = (
    ROOT
    / "custom_components"
    / "tater_satellite"
    / "conversation_display.py"
)
SPEC = importlib.util.spec_from_file_location(
    "tater_satellite_conversation_display", MODULE_PATH
)
assert SPEC is not None and SPEC.loader is not None
conversation_display = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = conversation_display
SPEC.loader.exec_module(conversation_display)


class ConversationDisplayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.state = conversation_display.ConversationDisplayState("echo-kitchen")

    def test_complete_home_assistant_turn(self) -> None:
        listening = self.state.pipeline_event("RUN_START", {})
        self.assertEqual(
            listening,
            {
                "turn_id": "echo-kitchen:1",
                "phase": "listening",
                "user_text": "",
                "user_final": False,
                "assistant_text": "",
                "assistant_final": False,
                "revision": 1,
            },
        )

        thinking = self.state.pipeline_event(
            "STT_END", {"text": "Turn on the kitchen lights"}
        )
        self.assertEqual(thinking["phase"], "thinking")
        self.assertEqual(thinking["user_text"], "Turn on the kitchen lights")
        self.assertTrue(thinking["user_final"])
        self.assertEqual(thinking["revision"], 2)

        replying = self.state.pipeline_event(
            "INTENT_END", {"speech": "Turning on the kitchen lights."}
        )
        self.assertEqual(replying["phase"], "replying")
        self.assertEqual(
            replying["assistant_text"], "Turning on the kitchen lights."
        )
        self.assertTrue(replying["assistant_final"])
        self.assertEqual(replying["revision"], 3)

        # TTS_START repeats the same final response in Home Assistant. Avoid a
        # duplicate wire update while retaining it as a fallback source.
        self.assertIsNone(
            self.state.pipeline_event(
                "TTS_START", {"text": "Turning on the kitchen lights."}
            )
        )

    def test_tts_text_is_used_when_intent_has_no_plain_speech(self) -> None:
        self.state.pipeline_event("RUN_START", {})
        self.state.pipeline_event("STT_END", {"text": "What time is it?"})
        self.assertIsNone(self.state.pipeline_event("INTENT_END", {}))

        replying = self.state.pipeline_event(
            "TTS_START", {"text": "It is 8:30 PM."}
        )
        self.assertEqual(replying["phase"], "replying")
        self.assertEqual(replying["assistant_text"], "It is 8:30 PM.")
        self.assertTrue(replying["assistant_final"])

    def test_new_run_resets_text_and_revision(self) -> None:
        self.state.pipeline_event("RUN_START", {})
        self.state.pipeline_event("STT_END", {"text": "First request"})
        self.state.pipeline_event("TTS_START", {"text": "First response"})

        next_turn = self.state.pipeline_event("RUN_START", {})
        self.assertEqual(next_turn["turn_id"], "echo-kitchen:2")
        self.assertEqual(next_turn["phase"], "listening")
        self.assertEqual(next_turn["user_text"], "")
        self.assertEqual(next_turn["assistant_text"], "")
        self.assertEqual(next_turn["revision"], 1)

    def test_stt_start_can_recover_a_missing_run_start(self) -> None:
        listening = self.state.pipeline_event("STT_START", {})
        self.assertEqual(listening["phase"], "listening")
        self.assertEqual(listening["revision"], 1)

    def test_assist_bridge_sends_display_protocol_to_screen_devices(self) -> None:
        source = (
            ROOT
            / "custom_components"
            / "tater_satellite"
            / "assist_satellite.py"
        ).read_text(encoding="utf-8")
        self.assertIn("ConversationDisplayState(runtime.device_id)", source)
        self.assertIn('self.runtime.capabilities.get("screen")', source)
        self.assertIn('"display.conversation", display_payload', source)


if __name__ == "__main__":
    unittest.main()
