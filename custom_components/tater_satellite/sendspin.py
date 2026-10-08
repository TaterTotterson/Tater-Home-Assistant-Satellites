"""Small Sendspin v1 source used by the Home Assistant media players.

Tater satellites expose a Sendspin player on TCP 8928.  The bridge is the
source: it decodes one Home Assistant media URL to 48 kHz stereo PCM and sends
the same timestamped timeline to every selected satellite.  Clock selection,
buffering, and drift correction belong to the Sendspin clients.
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import ipaddress
import json
import struct
import sys
import time
from array import array
from collections.abc import Awaitable, Callable
from typing import Any

import aiohttp

SENDSPIN_PORT = 8928
SENDSPIN_PATH = "/sendspin"
SENDSPIN_SAMPLE_RATE = 48_000
SENDSPIN_CHANNELS = 2
SENDSPIN_BIT_DEPTH = 16
SENDSPIN_AUDIO_MESSAGE = 4
SENDSPIN_CHUNK_FRAMES = 960  # 20 ms at 48 kHz
SENDSPIN_START_LEAD_US = 1_000_000
SENDSPIN_BUFFER_AHEAD_US = 800_000
SENDSPIN_HANDSHAKE_TIMEOUT = 20.0
SENDSPIN_END_MARGIN = 0.35


class SendspinError(RuntimeError):
    """The bridge could not deliver a Sendspin stream."""


def _text(value: Any) -> str:
    return str(value or "").strip()


def _integer(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(float(value))
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _monotonic_us() -> int:
    return time.monotonic_ns() // 1_000


def _websocket_url(host: str, port: int) -> str:
    token = _text(host)
    if not token:
        raise SendspinError("A satellite has no reachable Sendspin address")
    with contextlib.suppress(ValueError):
        address = ipaddress.ip_address(token.split("%", 1)[0])
        if address.version == 6:
            token = f"[{token}]"
    if any(character in token for character in ("/", "?", "#", "@")):
        raise SendspinError(f"Invalid Sendspin satellite address: {host}")
    return f"ws://{token}:{port}{SENDSPIN_PATH}"


def _audio_packet(timestamp_us: int, pcm: bytes) -> bytes:
    return (
        bytes((SENDSPIN_AUDIO_MESSAGE,))
        + struct.pack(">q", int(timestamp_us))
        + pcm
    )


def _transform_samples(pcm: bytes, *, mono: bool, volume_percent: int) -> bytes:
    """Apply a route's mono fold-down and trim to stereo S16LE PCM."""
    volume = _integer(volume_percent, 100, 0, 100)
    if not pcm or (not mono and volume == 100):
        return pcm
    samples = array("h")
    samples.frombytes(pcm)
    if sys.byteorder != "little":
        samples.byteswap()
    for index in range(0, len(samples) - 1, 2):
        left = samples[index]
        right = samples[index + 1]
        if mono:
            left = right = int((left + right) / 2)
        if volume != 100:
            left = int(left * volume / 100)
            right = int(right * volume / 100)
        samples[index] = left
        samples[index + 1] = right
    if sys.byteorder != "little":
        samples.byteswap()
    return samples.tobytes()


class _DelayLine:
    """Apply a fixed whole-frame delay while preserving packet length."""

    def __init__(self, delay_ms: Any) -> None:
        frames = round(
            _integer(delay_ms, 0, 0, 2_000) * SENDSPIN_SAMPLE_RATE / 1_000
        )
        self.frames = frames
        self._buffer = bytearray(frames * SENDSPIN_CHANNELS * 2)

    def apply(self, pcm: bytes) -> bytes:
        if not self._buffer:
            return pcm
        self._buffer.extend(pcm)
        result = bytes(self._buffer[: len(pcm)])
        del self._buffer[: len(pcm)]
        return result


class _Peer:
    """One plaintext Tater-compatible Sendspin player connection."""

    def __init__(self, session: aiohttp.ClientSession, target: dict[str, Any]) -> None:
        self.session = session
        self.device_id = _text(target.get("device_id") or target.get("selector"))
        self.host = _text(target.get("host"))
        self.port = _integer(target.get("port"), SENDSPIN_PORT, 1, 65_535)
        self.channel = _text(target.get("channel")).lower() or "stereo"
        self.trim_percent = _integer(target.get("trim_percent"), 100, 0, 100)
        self.delay = _DelayLine(target.get("delay_ms"))
        self.websocket: aiohttp.ClientWebSocketResponse | None = None
        self.receiver_task: asyncio.Task[None] | None = None
        self.send_lock = asyncio.Lock()
        self.hello_event = asyncio.Event()
        self.state_event = asyncio.Event()
        self.time_event = asyncio.Event()
        self.client_hello: dict[str, Any] = {}
        self.client_state = ""
        self.time_responses = 0
        self.error = ""
        self.closing = False

    async def open(self) -> None:
        try:
            self.websocket = await self.session.ws_connect(
                _websocket_url(self.host, self.port),
                heartbeat=15.0,
                autoclose=True,
                autoping=True,
                max_msg_size=2 * 1024 * 1024,
            )
        except Exception as err:
            raise SendspinError(
                f"Could not connect to {self.device_id or self.host}: {err}"
            ) from err
        self.receiver_task = asyncio.create_task(
            self._receive_loop(), name=f"tater_sendspin_receive_{self.device_id}"
        )
        await self.send_json(
            {
                "type": "server/hello",
                "payload": {
                    "server_id": "home-assistant-tater-satellites",
                    "name": "Home Assistant Tater Satellites",
                    "version": 1,
                    "active_roles": ["player@v1"],
                    "connection_reason": "playback",
                },
            }
        )

    async def _receive_loop(self) -> None:
        try:
            assert self.websocket is not None
            async for message in self.websocket:
                if message.type == aiohttp.WSMsgType.TEXT:
                    await self._handle_json(message.data)
                elif message.type in {
                    aiohttp.WSMsgType.CLOSE,
                    aiohttp.WSMsgType.CLOSED,
                    aiohttp.WSMsgType.ERROR,
                }:
                    break
        except asyncio.CancelledError:
            raise
        except Exception as err:
            if not self.closing:
                self.error = _text(err) or type(err).__name__
        finally:
            if not self.closing and not self.error:
                self.error = "the satellite closed its Sendspin connection"
            self.hello_event.set()
            self.state_event.set()
            self.time_event.set()

    async def _handle_json(self, raw_message: str) -> None:
        received_us = _monotonic_us()
        try:
            message = json.loads(raw_message)
        except (TypeError, ValueError):
            return
        if not isinstance(message, dict):
            return
        message_type = _text(message.get("type"))
        payload = (
            message.get("payload")
            if isinstance(message.get("payload"), dict)
            else {}
        )
        if message_type == "client/hello":
            self.client_hello = dict(payload)
            self.hello_event.set()
            return
        if message_type == "client/state":
            self.client_state = _text(payload.get("state")).lower()
            if self.client_state == "synchronized":
                self.state_event.set()
            return
        if message_type == "client/time":
            try:
                client_transmitted = int(payload.get("client_transmitted"))
            except (TypeError, ValueError):
                return
            await self.send_json(
                {
                    "type": "server/time",
                    "payload": {
                        "client_transmitted": client_transmitted,
                        "server_received": received_us,
                        "server_transmitted": _monotonic_us(),
                    },
                }
            )
            self.time_responses += 1
            if self.time_responses >= 8:
                self.time_event.set()
            return
        if message_type == "client/goodbye":
            self.error = (
                "the satellite left Sendspin "
                f"({_text(payload.get('reason')) or 'unknown reason'})"
            )
            self.hello_event.set()
            self.state_event.set()
            self.time_event.set()

    def _validate_hello(self) -> None:
        payload = self.client_hello
        try:
            version = int(payload.get("version") or 0)
        except (TypeError, ValueError):
            version = 0
        roles = {_text(value) for value in payload.get("supported_roles") or []}
        support = (
            payload.get("player@v1_support")
            if isinstance(payload.get("player@v1_support"), dict)
            else {}
        )
        formats = support.get("supported_formats") or []
        pcm_supported = any(
            isinstance(row, dict)
            and _text(row.get("codec")).lower() == "pcm"
            and _integer(row.get("channels"), 0, 0, 255) == SENDSPIN_CHANNELS
            and _integer(row.get("sample_rate"), 0, 0, 384_000)
            == SENDSPIN_SAMPLE_RATE
            and _integer(row.get("bit_depth"), 0, 0, 64) == SENDSPIN_BIT_DEPTH
            for row in formats
        )
        if version != 1 or "player@v1" not in roles or not pcm_supported:
            raise SendspinError(
                f"{self.device_id or self.host} does not support Sendspin v1 "
                "PCM 48 kHz stereo"
            )

    async def wait_ready(self) -> None:
        try:
            async with asyncio.timeout(SENDSPIN_HANDSHAKE_TIMEOUT):
                await asyncio.gather(
                    self.hello_event.wait(),
                    self.state_event.wait(),
                    self.time_event.wait(),
                )
        except TimeoutError as err:
            raise SendspinError(
                f"Timed out preparing {self.device_id or self.host} for Sendspin"
            ) from err
        if self.error:
            raise SendspinError(f"{self.device_id or self.host}: {self.error}")
        self._validate_hello()
        if self.client_state != "synchronized":
            raise SendspinError(
                f"{self.device_id or self.host} is busy with native audio"
            )

    async def send_json(self, message: dict[str, Any]) -> None:
        if self.websocket is None or self.websocket.closed:
            raise SendspinError(
                f"{self.device_id or self.host} Sendspin connection is closed"
            )
        raw = json.dumps(message, separators=(",", ":"), ensure_ascii=False)
        async with self.send_lock:
            await self.websocket.send_str(raw)

    async def send_audio(self, timestamp_us: int, pcm: bytes) -> None:
        if self.websocket is None or self.websocket.closed:
            raise SendspinError(
                f"{self.device_id or self.host} Sendspin connection is closed"
            )
        routed = _transform_samples(
            self.delay.apply(pcm),
            mono=self.channel == "mono",
            volume_percent=self.trim_percent,
        )
        async with self.send_lock:
            await self.websocket.send_bytes(_audio_packet(timestamp_us, routed))

    async def close(self) -> None:
        self.closing = True
        if self.websocket is not None and not self.websocket.closed:
            with contextlib.suppress(Exception):
                await self.websocket.close()
        if self.receiver_task is not None:
            self.receiver_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self.receiver_task


class SendspinStream:
    """Own one finite URL-to-Sendspin playback timeline."""

    def __init__(
        self,
        http_session: aiohttp.ClientSession,
        ffmpeg_binary: str,
        source_url: str,
        targets: list[dict[str, Any]],
        *,
        group_id: str,
        group_name: str,
        start_position_seconds: float = 0.0,
        duration_seconds: float | None = None,
        on_finished: Callable[[str], Awaitable[None] | None] | None = None,
    ) -> None:
        if not _text(ffmpeg_binary):
            raise SendspinError("Home Assistant FFmpeg is unavailable")
        if not _text(source_url).lower().startswith(("http://", "https://")):
            raise SendspinError("Sendspin playback requires an HTTP media URL")
        if not targets:
            raise SendspinError("No Sendspin satellites were selected")
        self.http_session = http_session
        self.ffmpeg_binary = ffmpeg_binary
        self.source_url = source_url
        self.targets = [dict(target) for target in targets]
        self.group_id = group_id
        self.group_name = group_name
        self.start_position_seconds = max(0.0, float(start_position_seconds or 0))
        self.duration_seconds = (
            max(0.0, float(duration_seconds))
            if duration_seconds is not None
            else None
        )
        self.on_finished = on_finished
        self.started_event = asyncio.Event()
        self.task: asyncio.Task[None] | None = None
        self.process: asyncio.subprocess.Process | None = None
        self.start_us = 0
        self.frames_sent = 0
        self.error = ""

    def bind_task(self, task: asyncio.Task[None]) -> None:
        self.task = task

    async def wait_started(self) -> None:
        if self.task is None:
            raise SendspinError("Sendspin stream task was not started")
        waiter = asyncio.create_task(self.started_event.wait())
        try:
            done, _pending = await asyncio.wait(
                {waiter, self.task},
                timeout=SENDSPIN_HANDSHAKE_TIMEOUT + 10.0,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if not done:
                raise SendspinError("Timed out starting Sendspin playback")
            if self.task in done:
                await self.task
            if self.error:
                raise SendspinError(self.error)
            if not self.started_event.is_set():
                raise SendspinError("The Sendspin media source contained no audio")
        finally:
            waiter.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await waiter

    def position_seconds(self) -> float:
        if self.start_us <= 0:
            return self.start_position_seconds
        elapsed = max(0.0, (_monotonic_us() - self.start_us) / 1_000_000)
        position = self.start_position_seconds + elapsed
        if self.duration_seconds is not None:
            return min(position, self.duration_seconds)
        return position

    async def stop(self) -> None:
        if self.task is None or self.task.done():
            return
        self.task.cancel()
        if self.task is asyncio.current_task():
            return
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await self.task

    async def _broadcast_json(
        self, peers: list[_Peer], message: dict[str, Any]
    ) -> None:
        await asyncio.gather(*(peer.send_json(message) for peer in peers))

    async def _broadcast_audio(
        self, peers: list[_Peer], timestamp_us: int, pcm: bytes
    ) -> None:
        await asyncio.gather(
            *(peer.send_audio(timestamp_us, pcm) for peer in peers)
        )

    async def _start_ffmpeg(self) -> asyncio.subprocess.Process:
        command = [
            self.ffmpeg_binary,
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
        ]
        if self.start_position_seconds > 0:
            command.extend(("-ss", f"{self.start_position_seconds:.3f}"))
        command.extend(
            (
                "-i",
                self.source_url,
                "-map",
                "0:a:0",
                "-vn",
                "-sn",
                "-dn",
                "-map_metadata",
                "-1",
                "-ar",
                str(SENDSPIN_SAMPLE_RATE),
                "-ac",
                str(SENDSPIN_CHANNELS),
                "-c:a",
                "pcm_s16le",
                "-f",
                "s16le",
                "pipe:1",
            )
        )
        try:
            return await asyncio.create_subprocess_exec(
                *command,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except (OSError, ValueError) as err:
            raise SendspinError(
                f"Could not start Home Assistant FFmpeg: {err}"
            ) from err

    async def _close_process(self) -> None:
        process = self.process
        if process is None or process.returncode is not None:
            return
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=2.0)
        except TimeoutError:
            process.kill()
            with contextlib.suppress(Exception):
                await process.wait()

    async def run(self) -> None:
        """Connect every player, decode the source, and publish its timeline."""
        peers = [_Peer(self.http_session, target) for target in self.targets]
        stream_started = False
        failure = ""
        try:
            await asyncio.gather(*(peer.open() for peer in peers))
            await asyncio.gather(*(peer.wait_ready() for peer in peers))
            # Let each client commit its eighth time sample before audio arrives.
            await asyncio.sleep(0.1)
            self.process = await self._start_ffmpeg()
            assert self.process.stdout is not None

            await self._broadcast_json(
                peers,
                {
                    "type": "group/update",
                    "payload": {
                        "playback_state": "playing",
                        "group_id": self.group_id,
                        "group_name": self.group_name,
                    },
                },
            )
            await self._broadcast_json(
                peers,
                {
                    "type": "stream/start",
                    "payload": {
                        "player": {
                            "codec": "pcm",
                            "sample_rate": SENDSPIN_SAMPLE_RATE,
                            "channels": SENDSPIN_CHANNELS,
                            "bit_depth": SENDSPIN_BIT_DEPTH,
                        }
                    },
                },
            )
            stream_started = True

            frame_bytes = SENDSPIN_CHANNELS * (SENDSPIN_BIT_DEPTH // 8)
            chunk_bytes = SENDSPIN_CHUNK_FRAMES * frame_bytes
            pending = bytearray()
            self.start_us = _monotonic_us() + SENDSPIN_START_LEAD_US

            async def publish(chunk: bytes) -> None:
                timestamp_us = self.start_us + round(
                    self.frames_sent * 1_000_000 / SENDSPIN_SAMPLE_RATE
                )
                send_at_us = timestamp_us - SENDSPIN_BUFFER_AHEAD_US
                delay = (send_at_us - _monotonic_us()) / 1_000_000
                if delay > 0:
                    await asyncio.sleep(delay)
                await self._broadcast_audio(peers, timestamp_us, chunk)
                self.frames_sent += SENDSPIN_CHUNK_FRAMES
                self.started_event.set()

            while True:
                chunk = await self.process.stdout.read(chunk_bytes - len(pending))
                if not chunk:
                    break
                pending.extend(chunk)
                if len(pending) >= chunk_bytes:
                    await publish(bytes(pending[:chunk_bytes]))
                    del pending[:chunk_bytes]

            return_code = await self.process.wait()
            if return_code != 0:
                detail = ""
                if self.process.stderr is not None:
                    detail = (await self.process.stderr.read()).decode(
                        "utf-8", errors="replace"
                    ).strip()
                raise SendspinError(
                    detail
                    or f"FFmpeg exited with status {return_code} while decoding audio"
                )
            if pending:
                pending.extend(b"\x00" * (chunk_bytes - len(pending)))
                await publish(bytes(pending))
            if self.frames_sent <= 0:
                raise SendspinError("The Sendspin media source contained no audio")

            maximum_delay_frames = max((peer.delay.frames for peer in peers), default=0)
            flush_chunks = (
                maximum_delay_frames + SENDSPIN_CHUNK_FRAMES - 1
            ) // SENDSPIN_CHUNK_FRAMES
            silence = b"\x00" * chunk_bytes
            for _index in range(flush_chunks):
                await publish(silence)

            audible_end_us = self.start_us + round(
                self.frames_sent * 1_000_000 / SENDSPIN_SAMPLE_RATE
            )
            remaining = (audible_end_us - _monotonic_us()) / 1_000_000
            if remaining > 0:
                await asyncio.sleep(remaining)
            await asyncio.sleep(SENDSPIN_END_MARGIN)
        except asyncio.CancelledError:
            raise
        except Exception as err:
            failure = _text(err) or type(err).__name__
            self.error = failure
            raise
        finally:
            if stream_started:
                with contextlib.suppress(Exception):
                    await self._broadcast_json(
                        peers,
                        {"type": "stream/end", "payload": {"roles": ["player"]}},
                    )
                with contextlib.suppress(Exception):
                    await self._broadcast_json(
                        peers,
                        {
                            "type": "group/update",
                            "payload": {
                                "playback_state": "stopped",
                                "group_id": self.group_id,
                                "group_name": self.group_name,
                            },
                        },
                    )
            await self._close_process()
            await asyncio.gather(*(peer.close() for peer in peers))
            if self.on_finished is not None:
                result = self.on_finished(failure)
                if inspect.isawaitable(result):
                    await result
