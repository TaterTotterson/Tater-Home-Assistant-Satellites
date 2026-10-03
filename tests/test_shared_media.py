"""Exercise the bridge's one-upstream stereo media spool without HA imports."""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest import mock

from aiohttp import ClientSession, web


COMPONENT = Path(__file__).resolve().parents[1] / "custom_components" / "tater_satellite"
package = types.ModuleType("tater_satellite_relay_test")
package.__path__ = [str(COMPONENT)]
const = types.ModuleType("tater_satellite_relay_test.const")
const.API_BASE_PATH = "/api/tater/satellite/v1"
spec = importlib.util.spec_from_file_location(
    "tater_satellite_relay_test.shared_media", COMPONENT / "shared_media.py"
)
assert spec is not None and spec.loader is not None
shared_media = importlib.util.module_from_spec(spec)
with mock.patch.dict(
    sys.modules,
    {
        "tater_satellite_relay_test": package,
        "tater_satellite_relay_test.const": const,
        "tater_satellite_relay_test.shared_media": shared_media,
    },
):
    spec.loader.exec_module(shared_media)


class SharedMediaTests(unittest.IsolatedAsyncioTestCase):
    async def test_two_stereo_readers_receive_one_identical_upstream(self) -> None:
        calls = 0
        release = asyncio.Event()

        async def source(request: web.Request) -> web.StreamResponse:
            nonlocal calls
            calls += 1
            response = web.StreamResponse(headers={"Content-Type": "audio/mpeg"})
            await response.prepare(request)
            await response.write(b"a" * shared_media.READY_BYTES)
            await release.wait()
            await response.write(b"b" * 8192)
            await response.write_eof()
            return response

        app = web.Application()
        app.router.add_get("/track.mp3", source)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        try:
            with tempfile.TemporaryDirectory() as directory:
                async with ClientSession() as session:
                    store = shared_media.SharedMediaStore(session, Path(directory))
                    try:
                        relay = await store.create(
                            f"http://127.0.0.1:{port}/track.mp3",
                            "track.mp3",
                            duration=3600,
                        )
                        self.assertEqual(relay.retention_seconds, 4200)
                        self.assertIn("/media/shared/", relay.url_for("http://ha.local:8123"))
                        self.assertIsNone(await store.get(relay.id, "wrong-token"))
                        self.assertIs(await store.get(relay.id, relay.token), relay)
                        left = relay.chunks()
                        right = relay.chunks()
                        self.assertEqual(await anext(left), b"a" * shared_media.READY_BYTES)
                        self.assertEqual(await anext(right), b"a" * shared_media.READY_BYTES)
                        release.set()
                        self.assertEqual(b"".join([chunk async for chunk in left]), b"b" * 8192)
                        self.assertEqual(b"".join([chunk async for chunk in right]), b"b" * 8192)
                        self.assertEqual(calls, 1)
                        self.assertEqual(relay.media_type, "audio/mpeg")
                        self.assertTrue(relay.complete)
                        self.assertEqual(relay.path.read_bytes(), b"a" * shared_media.READY_BYTES + b"b" * 8192)
                        relay.completed_at = time.time() - 11 * 60
                        relay.last_access_at = relay.completed_at
                        await store.prune()
                        self.assertIn(relay.id, store.relays)
                        relay.completed_at = time.time() - 4201
                        relay.last_access_at = relay.completed_at
                        await store.prune()
                        self.assertNotIn(relay.id, store.relays)
                    finally:
                        release.set()
                        await store.close()
        finally:
            release.set()
            await runner.cleanup()

    async def test_failed_source_does_not_leave_a_spool(self) -> None:
        async def fail(_request: web.Request) -> web.Response:
            return web.Response(status=502)

        app = web.Application()
        app.router.add_get("/bad.mp3", fail)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        try:
            with tempfile.TemporaryDirectory() as directory:
                async with ClientSession() as session:
                    store = shared_media.SharedMediaStore(session, Path(directory))
                    try:
                        with self.assertRaises(shared_media.SharedMediaError):
                            await store.create(f"http://127.0.0.1:{port}/bad.mp3", "bad.mp3")
                        self.assertEqual(list(Path(directory).iterdir()), [])
                        self.assertEqual(store.relays, {})
                    finally:
                        await store.close()
        finally:
            await runner.cleanup()

    async def test_stopping_live_playback_closes_upstream_and_prunes_spool(self) -> None:
        release = asyncio.Event()

        async def source(request: web.Request) -> web.StreamResponse:
            response = web.StreamResponse(headers={"Content-Type": "audio/mpeg"})
            await response.prepare(request)
            await response.write(b"a" * shared_media.READY_BYTES)
            await release.wait()
            return response

        app = web.Application()
        app.router.add_get("/live.mp3", source)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        try:
            with tempfile.TemporaryDirectory() as directory:
                async with ClientSession() as session:
                    store = shared_media.SharedMediaStore(session, Path(directory))
                    try:
                        relay = await store.create(
                            f"http://127.0.0.1:{port}/live.mp3", "live.mp3"
                        )
                        self.assertFalse(relay.complete)
                        await store.release(relay.id)
                        self.assertTrue(relay.complete)
                        self.assertTrue(relay.released)
                        self.assertIsNone(await store.reuse(relay.id, relay.source_url))
                        relay.completed_at -= 61
                        relay.last_access_at -= 61
                        await store.prune()
                        self.assertEqual(store.relays, {})
                        self.assertEqual(list(Path(directory).iterdir()), [])
                    finally:
                        release.set()
                        await store.close()
        finally:
            release.set()
            await runner.cleanup()
