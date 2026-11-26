from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
PAIRING_PATH = ROOT / "custom_components" / "tater_satellite" / "pairing.py"
SPEC = importlib.util.spec_from_file_location("tater_satellite_pairing", PAIRING_PATH)
assert SPEC is not None and SPEC.loader is not None
pairing = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pairing)


class PairingRetryTests(unittest.TestCase):
    def _retry(self, **overrides: object) -> str:
        values: dict[str, object] = {
            "supplied_code": "123-456",
            "pairing_code": "123456",
            "claimed_device_id": "s3box-05469c",
            "claimed_hardware_id": "3c842705469c",
            "device_token": "retry-safe-token",
            "retry_expires_at": 1030.0,
            "device_id": "s3box-05469c",
            "hardware_id": "3c:84:27:05:46:9c",
            "now": 1000.0,
        }
        values.update(overrides)
        return pairing.pairing_retry_token(**values)

    def test_same_device_can_recover_pending_token(self) -> None:
        self.assertEqual(self._retry(), "retry-safe-token")

    def test_different_identity_cannot_recover_pending_token(self) -> None:
        self.assertEqual(self._retry(device_id="s3box-ffffff"), "")
        self.assertEqual(self._retry(hardware_id="ffffffffffff"), "")
        self.assertEqual(self._retry(supplied_code="654321"), "")

    def test_expired_retry_cannot_recover_pending_token(self) -> None:
        self.assertEqual(self._retry(now=1030.0), "")


class AuthFailureTrackerTests(unittest.TestCase):
    def key(self, value):
        return pairing.rejected_credential_key(value)

    def test_only_formatting_of_six_digit_codes_is_canonicalized(self):
        self.assertEqual(self.key("123456"), self.key("123-456"))
        self.assertEqual(self.key("123456"), self.key("123 456"))
        self.assertNotEqual(self.key("123456"), self.key("123457"))
        self.assertNotEqual(self.key("token-123456"), self.key("token123456"))
        self.assertNotEqual(self.key("token-123456"), self.key("123456"))

    def test_continuous_retries_stay_suppressed_beyond_the_idle_timeout(self):
        tracker = pairing.AuthFailureTracker(idle_seconds=30)
        self.assertTrue(tracker.is_new_failure("ip", self.key("typo"), now=0))
        for now in (29, 58, 87, 116, 145):
            self.assertFalse(tracker.is_new_failure("ip", self.key("typo"), now=now))
        self.assertTrue(tracker.is_new_failure("ip", self.key("typo"), now=175))

    def test_new_credentials_and_new_addresses_are_reported(self):
        tracker = pairing.AuthFailureTracker()
        self.assertTrue(tracker.is_new_failure("ip-one", self.key("typo"), now=0))
        self.assertTrue(tracker.is_new_failure("ip-one", self.key("different"), now=1))
        self.assertTrue(tracker.is_new_failure("ip-two", self.key("typo"), now=2))
        self.assertFalse(tracker.is_new_failure("ip-one", self.key("typo"), now=3))

    def test_tracking_is_bounded_and_recent_retry_entries_are_retained(self):
        tracker = pairing.AuthFailureTracker(max_entries=2)
        tracker.is_new_failure("ip", self.key("first"), now=0)
        tracker.is_new_failure("ip", self.key("second"), now=1)
        self.assertFalse(tracker.is_new_failure("ip", self.key("first"), now=2))
        tracker.is_new_failure("ip", self.key("third"), now=3)
        self.assertEqual(len(tracker._seen), 2)
        self.assertFalse(tracker.is_new_failure("ip", self.key("first"), now=4))
        self.assertTrue(tracker.is_new_failure("ip", self.key("second"), now=5))
        self.assertEqual(len(tracker._seen), 2)
        self.assertTrue(
            all(isinstance(key[1], bytes) and len(key[1]) == 32 for key in tracker._seen)
        )

    def test_idle_entries_are_removed_and_invalid_limits_are_rejected(self):
        tracker = pairing.AuthFailureTracker(idle_seconds=10)
        tracker.is_new_failure("ip", self.key("first"), now=0)
        tracker.is_new_failure("ip", self.key("second"), now=1)
        tracker.is_new_failure("ip", self.key("third"), now=11)
        self.assertEqual(len(tracker._seen), 1)
        with self.assertRaises(ValueError):
            pairing.AuthFailureTracker(max_entries=0)
        with self.assertRaises(ValueError):
            pairing.AuthFailureTracker(idle_seconds=0)


if __name__ == "__main__":
    unittest.main()
