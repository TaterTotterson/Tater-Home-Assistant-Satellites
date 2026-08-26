from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
OTA_PATH = ROOT / "custom_components" / "tater_satellite" / "ota.py"
SPEC = importlib.util.spec_from_file_location("tater_satellite_ota", OTA_PATH)
assert SPEC is not None and SPEC.loader is not None
ota = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = ota
SPEC.loader.exec_module(ota)


class OtaCompletionTests(unittest.TestCase):
    def state(self):
        state = ota.OtaState()
        state.begin("native-voicepe-0.3.13", 4, now=100.0)
        return state

    def test_writing_progress_waits_for_reboot_verification(self) -> None:
        state = self.state()

        state.apply_status(
            {"status": "writing", "progress": 95, "message": "OTA writing"}
        )

        self.assertTrue(state.in_progress)
        self.assertEqual(95, state.progress)

    def test_pre_reboot_complete_is_reserved_at_99_percent(self) -> None:
        state = self.state()

        state.apply_status({"status": "complete", "progress": 100})

        self.assertTrue(state.in_progress)
        self.assertEqual(99, state.progress)
        self.assertIn("reconnect", state.message)

    def test_expected_version_reconnect_completes_when_status_was_missed(self) -> None:
        state = self.state()

        state.note_disconnect()
        state.note_reconnect(5, "native-voicepe-0.3.13")

        self.assertFalse(state.in_progress)
        self.assertEqual(100, state.progress)
        self.assertIn("verified", state.message)

    def test_same_connection_does_not_complete(self) -> None:
        state = self.state()

        state.note_reconnect(4, "native-voicepe-0.3.13")

        self.assertTrue(state.in_progress)
        self.assertEqual(0, state.progress)

    def test_old_version_reconnect_reports_rollback(self) -> None:
        state = self.state()

        state.note_disconnect()
        state.note_reconnect(5, "native-voicepe-0.3.11")

        self.assertFalse(state.in_progress)
        self.assertIn("native-voicepe-0.3.11", state.message)
        self.assertIn("native-voicepe-0.3.13", state.message)

    def test_device_error_is_returned(self) -> None:
        state = self.state()

        state.apply_status(
            {
                "status": "error",
                "progress": 95,
                "message": "OTA failed during ota end",
            }
        )

        self.assertFalse(state.in_progress)
        self.assertEqual("OTA failed during ota end", state.message)

    def test_missing_reconnect_times_out(self) -> None:
        state = self.state()

        expired = state.expire(state.attempt, now=401.0)

        self.assertTrue(expired)
        self.assertFalse(state.in_progress)
        self.assertIn("Timed out", state.message)

    def test_previous_attempt_timeout_cannot_fail_a_new_attempt(self) -> None:
        state = self.state()
        old_attempt = state.attempt
        state.begin("native-voicepe-0.3.14", 5, now=200.0)

        expired = state.expire(old_attempt, now=1000.0)

        self.assertFalse(expired)
        self.assertTrue(state.in_progress)


if __name__ == "__main__":
    unittest.main()
