"""Trainer delivery diagnostics remain separate from desired capture settings."""

import ast
from pathlib import Path
import unittest


MANAGER = (
    Path(__file__).resolve().parents[1]
    / "custom_components/tater_satellite/manager.py"
)


def capture_snapshot(status):
    nodes = [
        node
        for node in ast.parse(MANAGER.read_text()).body
        if isinstance(node, ast.FunctionDef)
        and node.name in {"_as_int", "_trainer_capture_snapshot"}
    ]
    scope = {"Any": object, "text": lambda value: str(value or "").strip()}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(MANAGER), "exec"), scope)
    return scope["_trainer_capture_snapshot"](status)


class TrainerCaptureStatusTests(unittest.TestCase):
    def test_missing_or_older_reports_do_not_claim_success(self):
        for status in ({}, {"wake_engine": None}, {"wake_engine": {"capture": {}}}):
            with self.subTest(status=status):
                self.assertEqual(capture_snapshot(status), {"reported": False})

    def test_pending_failed_and_successful_counts_are_independent(self):
        status = {
            "free_internal_heap": 3100,
            "wake_engine": {
                "capture": {
                    "upload_pending": True,
                    "uploads": 4,
                    "upload_failures": 2,
                    "upload_deferred": 3,
                    "upload_skipped": 1,
                    "last_error": "upload deferred during voice activity",
                    "last_event_type": "wake_detected",
                    "private": "do not forward",
                }
            },
        }
        actual = capture_snapshot(status)
        self.assertTrue(actual["reported"])
        self.assertTrue(actual["upload_pending"])
        self.assertFalse(actual["upload_running"])
        self.assertEqual(actual["uploads"], 4)
        self.assertEqual(actual["upload_failures"], 2)
        self.assertEqual(actual["upload_deferred"], 3)
        self.assertEqual(actual["upload_skipped"], 1)
        self.assertEqual(actual["free_internal_heap"], 3100)
        self.assertNotIn("private", actual)
        self.assertIn("private", status["wake_engine"]["capture"])

    def test_unavailable_memory_is_distinct_from_zero_and_bad_counts_are_safe(self):
        status = {"wake_engine": {"capture": {"uploads": -1, "upload_failures": "bad"}}}
        actual = capture_snapshot(status)
        self.assertEqual(actual["uploads"], 0)
        self.assertEqual(actual["upload_failures"], 0)
        self.assertIsNone(actual["free_internal_heap"])
        status["free_internal_heap"] = 0
        self.assertEqual(capture_snapshot(status)["free_internal_heap"], 0)


if __name__ == "__main__":
    unittest.main()
