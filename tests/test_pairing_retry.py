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


if __name__ == "__main__":
    unittest.main()
