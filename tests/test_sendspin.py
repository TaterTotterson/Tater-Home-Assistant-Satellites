from __future__ import annotations

from array import array
import importlib.util
from pathlib import Path
import struct
import sys
from types import ModuleType
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "custom_components" / "tater_satellite" / "sendspin.py"
SPEC = importlib.util.spec_from_file_location("tater_satellite_sendspin", SOURCE)
assert SPEC is not None and SPEC.loader is not None
sendspin = importlib.util.module_from_spec(SPEC)
try:
    import aiohttp  # noqa: F401
except ModuleNotFoundError:
    aiohttp_stub = ModuleType("aiohttp")
    aiohttp_stub.ClientSession = object
    aiohttp_stub.ClientWebSocketResponse = object
    aiohttp_stub.WSMsgType = ModuleType("WSMsgType")
    sys.modules["aiohttp"] = aiohttp_stub
SPEC.loader.exec_module(sendspin)


def _pcm(samples: list[int]) -> bytes:
    values = array("h", samples)
    if sys.byteorder != "little":
        values.byteswap()
    return values.tobytes()


def _samples(pcm: bytes) -> list[int]:
    values = array("h")
    values.frombytes(pcm)
    if sys.byteorder != "little":
        values.byteswap()
    return list(values)


class SendspinWireTests(unittest.TestCase):
    def test_audio_packet_uses_v1_pcm_type_and_big_endian_timestamp(self) -> None:
        packet = sendspin._audio_packet(1_234_567, b"\x01\x02\x03\x04")

        self.assertEqual(packet[0], sendspin.SENDSPIN_AUDIO_MESSAGE)
        self.assertEqual(struct.unpack(">q", packet[1:9])[0], 1_234_567)
        self.assertEqual(packet[9:], b"\x01\x02\x03\x04")

    def test_mono_fold_down_and_trim_are_applied_per_route(self) -> None:
        result = sendspin._transform_samples(
            _pcm([1000, -500, 3000, 1000]),
            mono=True,
            volume_percent=50,
        )

        self.assertEqual(_samples(result), [125, 125, 1000, 1000])

    def test_delay_line_preserves_packet_length(self) -> None:
        delay = sendspin._DelayLine(20)
        packet = _pcm([100, -100] * sendspin.SENDSPIN_CHUNK_FRAMES)

        first = delay.apply(packet)
        second = delay.apply(packet)

        self.assertEqual(first, b"\x00" * len(packet))
        self.assertEqual(second, packet)

    def test_ipv6_sendspin_url_is_bracketed(self) -> None:
        self.assertEqual(
            sendspin._websocket_url("2001:db8::5", 8928),
            "ws://[2001:db8::5]:8928/sendspin",
        )


if __name__ == "__main__":
    unittest.main()
