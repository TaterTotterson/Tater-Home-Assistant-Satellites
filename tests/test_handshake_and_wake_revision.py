from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
MANAGER_PATH = ROOT / "custom_components" / "tater_satellite" / "manager.py"
SETTINGS_PATH = ROOT / "custom_components" / "tater_satellite" / "settings.py"
SPEC = importlib.util.spec_from_file_location(
    "tater_satellite_handshake_settings", SETTINGS_PATH
)
assert SPEC is not None and SPEC.loader is not None
settings = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(settings)


class HandshakeAndWakeRevisionTests(unittest.TestCase):
    def test_hello_ack_precedes_runtime_setup(self) -> None:
        source = MANAGER_PATH.read_text(encoding="utf-8")
        handler = source.split("async def async_handle_websocket(", 1)[1]

        self.assertLess(
            handler.index('"hello.ack"'),
            handler.index("runtime = self.runtimes[device_id]"),
        )
        self.assertLess(
            handler.index('"hello.ack"'),
            handler.index("await self._update_record_from_hello(runtime, payload)"),
        )

    def test_wake_model_revision_is_sent_to_firmware(self) -> None:
        revision = "a" * 64
        payload = settings.firmware_payload(
            {
                "wake_word": "custom_url",
                "wake_word_url": "https://example.test/hey.json",
                "wake_model_revision": revision,
            }
        )

        self.assertEqual(payload["wake_model_revision"], revision)

    def test_builtin_wake_word_clears_custom_revision(self) -> None:
        payload = settings.firmware_payload(
            {
                "wake_word": "hey_tater",
                "wake_model_revision": "stale-revision",
            }
        )

        self.assertEqual(payload["wake_model_revision"], "")


if __name__ == "__main__":
    unittest.main()
