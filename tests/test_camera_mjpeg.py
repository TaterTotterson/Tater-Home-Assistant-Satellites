from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PARSER_PATH = ROOT / "custom_components" / "tater_satellite" / "camera_mjpeg.py"
SPEC = importlib.util.spec_from_file_location(
    "tater_satellite_camera_mjpeg", PARSER_PATH
)
assert SPEC is not None and SPEC.loader is not None
camera_mjpeg = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(camera_mjpeg)


class MjpegFrameParserTests(unittest.TestCase):
    def test_extracts_frames_across_arbitrary_chunks(self) -> None:
        parser = camera_mjpeg.MjpegFrameParser(1024)
        first = b"\xff\xd8first\xff\xd9"
        second = b"\xff\xd8second\xff\xd9"

        self.assertEqual(parser.feed(b"--frame\r\nContent-Type: image/jpeg\r\n"), [])
        self.assertEqual(parser.feed(first[:5]), [])
        self.assertEqual(
            parser.feed(first[5:] + b"\r\n--frame\r\n" + second), [first, second]
        )

    def test_preserves_a_split_start_marker(self) -> None:
        parser = camera_mjpeg.MjpegFrameParser(1024)

        self.assertEqual(parser.feed(b"multipart header\xff"), [])
        self.assertEqual(parser.feed(b"\xd8jpeg\xff\xd9"), [b"\xff\xd8jpeg\xff\xd9"])

    def test_recovers_after_an_oversized_corrupt_frame(self) -> None:
        parser = camera_mjpeg.MjpegFrameParser(16)
        valid = b"\xff\xd8ok\xff\xd9"

        self.assertEqual(
            parser.feed(b"\xff\xd8" + b"x" * 20 + valid),
            [valid],
        )


if __name__ == "__main__":
    unittest.main()
