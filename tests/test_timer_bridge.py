from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "custom_components" / "tater_satellite" / "timers.py"
SPEC = importlib.util.spec_from_file_location("tater_satellite_timers", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
timers = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(timers)


class TimerBridgeTests(unittest.TestCase):
    @staticmethod
    def _timer(*, active: bool = True) -> SimpleNamespace:
        return SimpleNamespace(
            id="timer-1",
            name="pasta",
            is_active=active,
            seconds_left=290,
            created_seconds=300,
        )

    def test_started_timer_runs_on_satellite(self) -> None:
        command, payload = timers.timer_event_command("started", self._timer())

        self.assertEqual(command, "timer.arm")
        self.assertEqual(payload["id"], "timer-1")
        self.assertEqual(payload["name"], "pasta")
        self.assertEqual(payload["remaining_ms"], 290000)
        self.assertEqual(payload["original_duration_ms"], 300000)

    def test_active_update_rearms_same_timer(self) -> None:
        command, payload = timers.timer_event_command("updated", self._timer())

        self.assertEqual(command, "timer.arm")
        self.assertEqual(payload["id"], "timer-1")
        self.assertEqual(payload["remaining_ms"], 290000)

    def test_pause_and_cancel_clear_satellite_timer(self) -> None:
        paused = timers.timer_event_command("updated", self._timer(active=False))
        cancelled = timers.timer_event_command("cancelled", self._timer())

        expected = ("timer.clear", {"id": "timer-1", "source": "home_assistant"})
        self.assertEqual(paused, expected)
        self.assertEqual(cancelled, expected)

    def test_home_assistant_finish_does_not_duplicate_local_alarm(self) -> None:
        self.assertIsNone(timers.timer_event_command("finished", self._timer()))


if __name__ == "__main__":
    unittest.main()
