"""Small helpers for relaying FFmpeg MJPEG output to Echo screens."""

from __future__ import annotations

JPEG_START = b"\xff\xd8"
JPEG_END = b"\xff\xd9"


class MjpegFrameParser:
    """Extract complete JPEG images from a chunked multipart MJPEG stream."""

    def __init__(self, maximum_frame_bytes: int) -> None:
        self.maximum_frame_bytes = maximum_frame_bytes
        self._buffer = bytearray()

    def feed(self, chunk: bytes) -> list[bytes]:
        """Consume a stream chunk and return every complete valid-size JPEG."""
        if chunk:
            self._buffer.extend(chunk)
        frames: list[bytes] = []

        while self._buffer:
            start = self._buffer.find(JPEG_START)
            if start < 0:
                # Retain a trailing 0xff in case the SOI marker is split across
                # chunks; multipart headers and boundaries can be discarded.
                trailing_ff = self._buffer[-1:] == b"\xff"
                self._buffer.clear()
                if trailing_ff:
                    self._buffer.extend(b"\xff")
                break
            if start:
                del self._buffer[:start]

            end = self._buffer.find(JPEG_END, len(JPEG_START))
            if end >= 0:
                frame_end = end + len(JPEG_END)
                if frame_end <= self.maximum_frame_bytes:
                    frames.append(bytes(self._buffer[:frame_end]))
                    del self._buffer[:frame_end]
                    continue
                next_start = self._buffer.find(JPEG_START, len(JPEG_START))
                del self._buffer[: next_start if next_start >= 0 else frame_end]
                continue

            if len(self._buffer) <= self.maximum_frame_bytes:
                break

            # A corrupt or oversized frame must not prevent recovery at the
            # next JPEG marker.
            next_start = self._buffer.find(JPEG_START, len(JPEG_START))
            if next_start >= 0:
                del self._buffer[:next_start]
                continue
            trailing_ff = self._buffer[-1:] == b"\xff"
            self._buffer.clear()
            if trailing_ff:
                self._buffer.extend(b"\xff")
            break

        return frames
