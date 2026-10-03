"""One-upstream media spool shared by synchronized satellite players."""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import math
import os
import secrets
import tempfile
import time
import uuid
from pathlib import Path
from urllib.parse import quote

import aiohttp

from .const import API_BASE_PATH

CHUNK_BYTES = 8 * 1024
READY_BYTES = 4 * 1024
READY_TIMEOUT_SECONDS = 20.0
RETENTION_SECONDS = 10 * 60.0
MAX_IDLE_SECONDS = 12 * 60 * 60.0


class SharedMediaError(RuntimeError):
    """The shared upstream could not provide playable media."""


class SharedMediaRelay:
    """Spool a source once and let every satellite read the same bytes."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        root: Path,
        source_url: str,
        filename: str,
        duration: float | None,
    ) -> None:
        self.id = uuid.uuid4().hex
        self.token = secrets.token_urlsafe(32)
        self.session = session
        self.root = root
        self.source_url = source_url
        self.filename = Path(filename).name or "media.bin"
        self.path: Path | None = None
        self.media_type = "application/octet-stream"
        self.bytes_written = 0
        self.complete = False
        self.error = ""
        self.readers = 0
        self.last_access_at = time.time()
        self.completed_at = 0.0
        self.released = False
        try:
            expected = float(duration or 0)
        except (TypeError, ValueError):
            expected = 0.0
        self.retention_seconds = min(
            MAX_IDLE_SECONDS,
            max(RETENTION_SECONDS, expected + RETENTION_SECONDS)
            if math.isfinite(expected)
            else RETENTION_SECONDS,
        )
        self._changed = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        await asyncio.to_thread(self.root.mkdir, parents=True, exist_ok=True)
        handle, filename = await asyncio.to_thread(
            tempfile.mkstemp,
            prefix=f"relay-{self.id[:12]}-",
            suffix=Path(self.filename).suffix or ".bin",
            dir=str(self.root),
        )
        os.close(handle)
        self.path = Path(filename)
        self._task = asyncio.create_task(
            self._copy(), name=f"tater_media_relay_{self.id[:8]}"
        )
        try:
            await asyncio.wait_for(self._wait_ready(), READY_TIMEOUT_SECONDS)
        except (TimeoutError, SharedMediaError, asyncio.CancelledError):
            await self.close()
            raise

    async def _wait_ready(self) -> None:
        while self.bytes_written < READY_BYTES and not self.complete:
            self._changed.clear()
            await self._changed.wait()
        if self.bytes_written <= 0 or self.error:
            raise SharedMediaError(self.error or "The source produced no audio")

    async def _copy(self) -> None:
        try:
            timeout = aiohttp.ClientTimeout(sock_connect=10, sock_read=60)
            async with self.session.get(self.source_url, timeout=timeout) as response:
                response.raise_for_status()
                self.media_type = response.content_type or self.media_type
                assert self.path is not None
                with self.path.open("wb", buffering=0) as output:
                    async for chunk in response.content.iter_chunked(CHUNK_BYTES):
                        if chunk:
                            await asyncio.to_thread(output.write, chunk)
                            self.bytes_written += len(chunk)
                            self._changed.set()
        except asyncio.CancelledError:
            if self.released:
                self.error = "Playback stopped before the source completed"
            raise
        except Exception as err:
            self.error = str(err) or type(err).__name__
        finally:
            self.complete = True
            self.completed_at = time.time()
            self._changed.set()

    def url_for(self, base_url: str) -> str:
        return (
            f"{base_url.rstrip('/')}{API_BASE_PATH}/media/shared/"
            f"{self.id}/{quote(self.filename)}?token={quote(self.token)}"
        )

    async def chunks(self):
        """Stream an in-progress spool without opening a second upstream."""
        assert self.path is not None
        self.readers += 1
        self.last_access_at = time.time()
        cursor = 0
        try:
            with self.path.open("rb", buffering=0) as source:
                while True:
                    while cursor >= self.bytes_written and not self.complete:
                        self._changed.clear()
                        await self._changed.wait()
                    available = self.bytes_written - cursor
                    if available > 0:
                        chunk = await asyncio.to_thread(
                            source.read, min(CHUNK_BYTES, available)
                        )
                        if chunk:
                            cursor += len(chunk)
                            yield chunk
                            continue
                    if self.complete:
                        return
        finally:
            self.readers -= 1
            self.last_access_at = time.time()

    async def stop_source(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def close(self) -> None:
        await self.stop_source()
        if self.path is not None:
            with contextlib.suppress(OSError):
                await asyncio.to_thread(self.path.unlink)
            self.path = None


class SharedMediaStore:
    """Own short-lived, token-protected relays for one bridge instance."""

    def __init__(self, session: aiohttp.ClientSession, root: Path) -> None:
        self.session = session
        self.root = root
        self.relays: dict[str, SharedMediaRelay] = {}
        self._maintenance = asyncio.create_task(
            self._sweep(), name="tater_media_relay_sweep"
        )

    async def _sweep(self) -> None:
        try:
            while True:
                await asyncio.sleep(60)
                await self.prune()
        except asyncio.CancelledError:
            raise

    async def create(
        self, source_url: str, filename: str, duration: float | None = None
    ) -> SharedMediaRelay:
        await self.prune()
        relay = SharedMediaRelay(self.session, self.root, source_url, filename, duration)
        await relay.start()
        self.relays[relay.id] = relay
        return relay

    async def get(self, relay_id: str, token: str) -> SharedMediaRelay | None:
        await self.prune()
        relay = self.relays.get(relay_id)
        if relay is None or not hmac.compare_digest(relay.token, token):
            return None
        relay.last_access_at = time.time()
        return relay

    async def reuse(self, relay_id: str, source_url: str) -> SharedMediaRelay | None:
        """Keep seeking within the exact stream already heard by the pair."""
        await self.prune()
        relay = self.relays.get(relay_id)
        if relay is None or relay.released or relay.source_url != source_url:
            return None
        relay.last_access_at = time.time()
        return relay

    async def release(self, relay_id: str) -> None:
        """Stop an unused live upstream while briefly retaining its bytes."""
        relay = self.relays.get(relay_id)
        if relay is None or relay.released:
            return
        relay.released = True
        await relay.stop_source()
        relay.retention_seconds = min(relay.retention_seconds, 60.0)
        relay.last_access_at = time.time()

    async def prune(self) -> None:
        now = time.time()
        stale = [
            relay
            for relay in self.relays.values()
            if relay.readers == 0
            and (
                (
                    relay.complete
                    and now - max(relay.completed_at, relay.last_access_at)
                    >= relay.retention_seconds
                )
                or now - relay.last_access_at >= MAX_IDLE_SECONDS
            )
        ]
        for relay in stale:
            self.relays.pop(relay.id, None)
            await relay.close()

    async def close(self) -> None:
        self._maintenance.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._maintenance
        for relay in list(self.relays.values()):
            await relay.close()
        self.relays.clear()
